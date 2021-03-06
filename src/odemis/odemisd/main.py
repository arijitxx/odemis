#!/usr/bin/env python
# -*- coding: utf-8 -*-
'''
Created on 26 Mar 2012

@author: Éric Piel

Copyright © 2012-2014 Éric Piel, Delmic

This file is part of Odemis.

Odemis is free software: you can redistribute it and/or modify it under the terms 
of the GNU General Public License version 2 as published by the Free Software 
Foundation.

Odemis is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY; 
without even the implied warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR 
PURPOSE. See the GNU General Public License for more details.

You should have received a copy of the GNU General Public License along with 
Odemis. If not, see http://www.gnu.org/licenses/.
'''

import argparse
import grp
from logging import FileHandler
import logging
from odemis import model
import odemis
from odemis.model import ST_UNLOADED, ST_STARTING
from odemis.odemisd import modelgen
from odemis.odemisd.mdupdater import MetadataUpdater
from odemis.util.driver import BACKEND_RUNNING, BACKEND_DEAD, BACKEND_STOPPED, \
    get_backend_status, BACKEND_STARTING
import os
import signal
import stat
import sys
import threading
import time


status_to_xtcode = {BACKEND_RUNNING: 0,
                    BACKEND_DEAD: 1,
                    BACKEND_STOPPED: 2,
                    BACKEND_STARTING: 3,
                    }

class BackendContainer(model.Container):
    """
    A normal container which also terminates all the other containers when it
    terminates.
    """
    def __init__(self, model_file, create_sub_containers=False,
                dry_run=False, name=model.BACKEND_NAME):
        """
        inst_file (file): opened file that contains the yaml
        container (Container): container in which to instantiate the components
        create_sub_containers (bool): whether the leave components (components which
           have no children created separately) are running in isolated containers
        dry_run (bool): if True, it will check the semantic and try to instantiate the
          model without actually any driver contacting the hardware.
        """
        model.Container.__init__(self, name)

        self._model = model_file
        self._mdupdater = None
        self._inst_thread = None # thread running the component instantiation
        self._must_stop = threading.Event()
        self._dry_run = dry_run
        # TODO: have an argument to ask for disabling parallel start? same as create_sub_containers?

        # parse the instantiation file
        logging.debug("model instantiation file is: %s", self._model.name)
        try:
            self._instantiator = modelgen.Instantiator(model_file, self, create_sub_containers, dry_run)
            # save the model
            logging.info("model has been successfully parsed")
        except modelgen.ParseError as exp:
            raise ValueError("Error while parsing file %s:\n%s" % (self._model.name, exp))
        except modelgen.SemanticError as exp:
            raise ValueError("When instantiating file %s:\n%s" % (self._model.name, exp))
        except Exception:
            logging.exception("When instantiating file %s", self._model.name)
            raise IOError("Unexpected error at instantiation")

    def run(self):
        # Create the root
        mic = self._instantiator.instantiate_microscope()
        self.setRoot(mic)
        logging.debug("Root component %s created", mic.name)

        # Start by filling up the ghosts VA with all the components
        ghosts_names = set(self._instantiator.ast.keys()) - {mic.name}
        mic.ghosts.value = dict((n, ST_UNLOADED) for n in ghosts_names)

        # Start the metadata update
        # TODO: upgrade metadata updater to support online changes
        self._mdupdater = self.instantiate(MetadataUpdater,
                               {"name": "Metadata Updater", "microscope": mic})

        # Keep instantiating the other components in a separate thread
        self._inst_thread = threading.Thread(target=self._instantiate_forever,
                                             name="Component instantiator")
        self._inst_thread.start()

        if self._dry_run:
            # TODO: wait until all the components have been instantiated or one
            # error happened

            logging.info("model has been successfully validated, exiting")
            return    # everything went fine

        logging.info("Microscope is now available in container '%s'", self._name)

        # From now on, we'll really listen to external calls
        model.Container.run(self)

    def _instantiate_forever(self):
        """
        Thread continuously monitoring the components that need to be instantiated
        """
        try:
            # Hack warning: there is a bug in python when using lock (eg, logging)
            # and simultaneously using theads and process: is a thread acquires
            # a lock while a process is created, it will never be released.
            # See http://bugs.python.org/issue6721
            # To ensure this is not happening, we wait long enough that all (2)
            # threads have started (and logging nothing) before creating new processes.
            time.sleep(1)

            mic = self._instantiator.microscope
            failed = set() # set of str: name of components that failed recently
            while not self._must_stop.is_set():
                # Try to start simultaneously all the components that are
                # independent from each other
                nexts = set()
                while not nexts:
                    instantiated = set(c.name for c in mic.alive.value) | {mic.name}
                    nexts = self._instantiator.get_instantiables(instantiated)
                    # If still some non-failed component, immediately try again,
                    # otherwise give some time for things to get fixed or broken
                    nexts -= failed
                    if not nexts:
                        if self._must_stop.wait(10):
                            return
                        failed = set() # not recent anymore

                logging.debug("Trying to instantiate comp: %s", ", ".join(nexts))

                for n in nexts:
                    ghosts = mic.ghosts.value.copy()
                    if not n in ghosts:
                        logging.warning("going to instantiate %s but not a ghost", n)
                    # TODO: run each of them in a future, so that they start
                    # in parallel, and (bonus) when the future is done, check
                    # immediately which component can be started. The only
                    # difficulty is to ensure non-concurrent access to .ghosts
                    # and .alive .
                    try:
                        ghosts[n] = ST_STARTING
                        mic.ghosts.value = ghosts
                        newcmps = self._instantiate_component(n)
                    except ValueError:
                        # We now need to stop, but cannot call terminate()
                        # directly, as it would deadlock, waiting for us
                        threading.Thread(target=self.terminate).start()
                        return
                    if not newcmps:
                        failed.add(n)

        except Exception:
            logging.exception("Instantiator thread failed")
        finally:
            logging.debug("Instantiator thread finished")

    def _instantiate_component(self, name):
        """
        Instantiate a component and handle the outcome
        return (set of str): name of all the component instantiated, so it is an
          empty set if the component failed to instantiate (due to HwError)
        raise ValueError: if the component failed so badly to instantiate that
                          it's unlikely it'll ever instantiate
        """
        # TODO: use the AST from the microscope (instead of the original one
        # in _instantiator) to allow modifying it online?
        mic = self._instantiator.microscope
        ghosts = mic.ghosts.value.copy()
        try:
            comp = self._instantiator.instantiate_component(name)
        except model.HwError as exp:
            # HwError means: hardware problem, try again later
            logging.warning("Failed to start component %s due to device error: %s",
                            name, exp)
            ghosts[name] = exp
            mic.ghosts.value = ghosts
            return set()
        except Exception as exp:
            # Anything else means: driver is borked, give up
            # Exception might have happened remotely, so log it nicely
            logging.error("Failed to instantiate the model due to component %s", name)
            logging.info("Full traceback of the error follows", exc_info=1)
            try:
                remote_tb = exp._pyroTraceback
                logging.info("Remote exception %s", "".join(remote_tb))
            except AttributeError:
                pass
            raise ValueError("Failed to instantiate component %s" % name)
        else:
            children = self._instantiator.get_children(comp)
            dchildren = self._instantiator.get_delegated_children(name)
            newcmps = set(c for c in children if c.name in dchildren)
            mic.alive.value = mic.alive.value | newcmps
            # update ghosts by removing all the new components
            for n in dchildren:
                del ghosts[n]

            mic.ghosts.value = ghosts
            return dchildren

    def terminate(self):
        # Stop the component instantiator, to be sure it'll not restart the components
        self._must_stop.set()
        if self._inst_thread:
            self._inst_thread.join(10)
            if self._inst_thread.is_alive():
                logging.warning("Failed to stop the instantiator")
            else:
                self._inst_thread = None

        # Stop all the components
        if self._mdupdater:
            try:
                self._mdupdater.terminate()
            except Exception:
                logging.warning("Failed to terminate Metadata updater", exc_info=True)

        mic = self._instantiator.microscope
        alive = list(mic.alive.value)
        for comp in alive:
            logging.debug("Stopping comp %s", comp.name)
            # TODO: update the .alive VA every time a component is stopped?
            # maybe not necessary as we are finishing _everything_
            try:
                comp.terminate()
            except Exception:
                logging.warning("Failed to terminate component '%s'", comp.name, exc_info=True)

        try:
            mic.terminate()
        except Exception:
            logging.warning("Failed to terminate root", exc_info=True)

        # end all the (sub-)containers
        for container in self._instantiator.sub_containers:
            logging.debug("Stopping container %s", container)
            try:
                container.terminate()
            except Exception:
                logging.warning("Failed to terminate container %r", container, exc_info=True)

        # end ourself
        model.Container.terminate(self)

class BackendRunner(object):
    CONTAINER_ALL_IN_ONE = "1" # one backend container for everything
    CONTAINER_SEPARATED = "+" # each component is started in a separate container

    def __init__(self, model_file, daemon=False, dry_run=False, containement=CONTAINER_SEPARATED):
        """
        containement (CONTAINER_*): the type of container policy to use
        """
        self.model = model_file
        self.daemon = daemon
        self.dry_run = dry_run
        self.containement = containement

        self._container = None

        self._main_thread = threading.current_thread()
        signal.signal(signal.SIGINT, self.handle_signal)

    def set_base_group(self):
        """
        Change the current process to be running in the base group (odemis)
        raise:
            Exception in case it's not possible (lack of permissions...)
        """
        try:
            gid_base = grp.getgrnam(model.BASE_GROUP).gr_gid
        except KeyError:
            logging.exception(model.BASE_GROUP + " group doesn't exists.")
            raise

        try:
            os.setgid(gid_base)
        except OSError:
            logging.warning("Not enough permissions to run in group " + model.BASE_GROUP + ", trying anyway...")

        # everything created after must be rw by group
        os.umask(~(stat.S_IRUSR | stat.S_IWUSR | stat.S_IRGRP | stat.S_IWGRP))

    def mk_base_dir(self):
        """
        Create the base directory for communication between containers if it's not
        present yet. To create it, you likely need root permissions.
        raise:
            Exception in case it's not possible to create it (lack of permissions...)
        """
        if not os.path.exists(model.BASE_DIRECTORY):
            # it will raise an appropriate exception if it fails to create it
            os.mkdir(model.BASE_DIRECTORY)

    #        # change the group
    #        gid_base = grp.getgrnam(model.BASE_GROUP).gr_gid
    #        os.chown(model.BASE_DIRECTORY, -1, gid_base)
            # Files inside are all group odemis, and it can be listed by anyone
            os.chmod(model.BASE_DIRECTORY, stat.S_ISGID | stat.S_IRWXU | stat.S_IRWXG | stat.S_IROTH | stat.S_IXOTH)
            logging.debug("created directory " + model.BASE_DIRECTORY)
        elif not os.path.isdir(model.BASE_DIRECTORY):
            # the unlikely case it's a file
            logging.warning(model.BASE_DIRECTORY + " is not a directory, trying anyway...")

    def handle_signal(self, signum, frame):
        # TODO: ensure this is only processed by the main thread
        if threading.current_thread() == self._main_thread:
            logging.warning("Received signal %d: quitting", signum)
            self.stop()
        else:
            logging.info("Skipping signal %d in sub-thread", signum)

    def stop(self):
        self._container.terminate()
        self._container.close()

    def run(self):
        # change to odemis group and create the base directory
        try:
            self.set_base_group()
        except Exception:
            logging.error("Failed to get group " + model.BASE_GROUP)
            raise

        try:
            self.mk_base_dir()
        except Exception:
            logging.error("Failed to create back-end directory " + model.BASE_DIRECTORY)

        # create the root container
        try:
            # create daemon for containing the backend container
            if self.daemon:
                pid = os.fork()
                if pid:
                    logging.debug("Daemon started with pid %d", pid)
                    # TODO: we could try to contact the backend and see if it managed to start
                    return 0
                else:
                    self._main_thread = threading.current_thread()
        except Exception:
            logging.error("Failed to start daemon")
            raise

        if self.containement == BackendRunner.CONTAINER_SEPARATED:
            create_sub_containers = True
        else:
            create_sub_containers = False

        self._container = BackendContainer(self.model, create_sub_containers,
                                        dry_run=self.dry_run)

        try:
            self._container.run()
        except Exception:
            self.stop()
            raise

def rotateLog(filename, maxBytes, backupCount=0):
    """
    Rotate the log file if it's bigger than the maxBytes.
    Based on RotatingFileHandler.doRollover()
    """
    if not os.path.exists(filename):
        return

    if os.path.getsize(filename) < maxBytes:
        return

    # Rename the older logs
    if backupCount > 0:
        for i in range(backupCount, 0, -1):
            if i > 1:
                sfn = "%s.%d" % (filename, i - 1)
            else:
                sfn = filename
            dfn = "%s.%d" % (filename, i)
            # print "%s -> %s" % (sfn, dfn)
            if os.path.exists(sfn):
                if os.path.exists(dfn):
                    os.remove(dfn)
                os.rename(sfn, dfn)
    else:
        os.remove(filename)

# This is the cli interface of odemisd, which allows to start the back-end
# It parses the command line and accordingly reads the microscope instantiation
# file, generates a model out of it, and then provides it to the front-end
def main(args):
    """
    Contains the console handling code for the daemon
    args is the list of arguments passed
    return (int): value to return to the OS as program exit code
    """

    #print args
    # arguments handling
    parser = argparse.ArgumentParser(description=odemis.__fullname__)

    parser.add_argument('--version', dest="version", action='store_true',
                        help="show program's version number and exit")
    dm_grp = parser.add_argument_group('Daemon management')
    dm_grpe = dm_grp.add_mutually_exclusive_group()
    dm_grpe.add_argument("--kill", "-k", dest="kill", action="store_true", default=False,
                         help="Kill the running back-end")
    dm_grpe.add_argument("--check", dest="check", action="store_true", default=False,
                        help="Check for a running back-end (only returns exit code)")
    dm_grpe.add_argument("--daemonize", "-D", action="store_true", dest="daemon",
                         default=False, help="Daemonize the back-end")
    opt_grp = parser.add_argument_group('Options')
    opt_grp.add_argument('--validate', dest="validate", action="store_true", default=False,
                         help="Validate the microscope description file and exit")
    dm_grpe.add_argument("--debug", action="store_true", dest="debug",
                         default=False, help="Activate debug mode, where everything runs in one process")
    opt_grp.add_argument("--log-level", dest="loglev", metavar="LEVEL", type=int,
                         default=0, help="Set verbosity level (0-2, default = 0)")
    opt_grp.add_argument("--log-target", dest="logtarget", metavar="{auto,stderr,filename}",
                         default="auto", help="Specify the log target (auto, stderr, filename)")
    parser.add_argument("model", metavar="file.odm.yaml", nargs='?', type=open,
                        help="Microscope model instantiation file (*.odm.yaml)")

    options = parser.parse_args(args[1:])

    # Cannot use the internal feature, because it doesn't support multiline
    if options.version:
        print (odemis.__fullname__ + " " + odemis.__version__ + "\n" +
               odemis.__copyright__ + "\n" +
               "Licensed under the " + odemis.__license__)
        return 0

    # Set up logging before everything else
    if options.loglev < 0:
        parser.error("log-level must be positive.")
    loglev_names = [logging.WARNING, logging.INFO, logging.DEBUG]
    loglev = loglev_names[min(len(loglev_names) - 1, options.loglev)]

    # auto = {odemis.log if daemon, stderr otherwise}
    if options.logtarget == "auto":
        # default to SysLogHandler ?
        if options.daemon:
            options.logtarget = "odemis.log"
        else:
            options.logtarget = "stderr"
    if options.logtarget == "stderr":
        handler = logging.StreamHandler()
    else:
        # Rotate the log, with max 5*50Mb used.
        # Note: we used to rely on RotatingFileHandler, but due to multi-
        # processes, it would be rotated multiple times every time it reached the
        # limit. So now, just do it at startup, and hope it doesn't reach huge
        # size in one run.
        rotateLog(options.logtarget, maxBytes=50 * (2 ** 20), backupCount=5)
        handler = FileHandler(options.logtarget)
    logging.getLogger().setLevel(loglev)
    handler.setFormatter(logging.Formatter('%(asctime)s (%(module)s) %(levelname)s: %(message)s'))
    logging.getLogger().addHandler(handler)

    if loglev <= logging.DEBUG:
        # Activate also Pyro logging
        # TODO: options.logtarget
        pyrolog = logging.getLogger("Pyro4")
        pyrolog.setLevel(min(pyrolog.getEffectiveLevel(), logging.INFO))

    # Useful to debug cases of multiple conflicting installations
    logging.info("Starting Odemis back-end (from %s)", __file__)

    if options.validate and (options.kill or options.check or options.daemon):
        logging.error("Impossible to validate a model and manage the daemon simultaneously")
        return 127

    # Daemon management
    # python-daemon is a fancy library but seems to do too many things for us.
    # We just need to contact the backend and see what happens
    status = get_backend_status()
    if options.check:
        logging.info("Status of back-end is %s", status)
        return status_to_xtcode[status]

    try:
        if options.kill:
            if status != BACKEND_RUNNING:
                raise IOError("No running back-end to kill")
            backend = model.getContainer(model.BACKEND_NAME)
            backend.terminate()
            return 0

        # check if there is already a backend running
        if status == BACKEND_RUNNING:
            raise IOError("Back-end already running, cannot start a new one")

        if options.model is None:
            raise ValueError("No microscope model instantiation file provided")

        if options.debug:
            cont_pol = BackendRunner.CONTAINER_ALL_IN_ONE
        else:
            cont_pol = BackendRunner.CONTAINER_SEPARATED

        # let's become the back-end for real
        runner = BackendRunner(options.model, options.daemon,
                               dry_run=options.validate, containement=cont_pol)
        runner.run()
    except ValueError as exp:
        logging.error("%s", exp)
        return 127
    except IOError as exp:
        logging.error("%s", exp)
        return 129
    except Exception:
        logging.exception("Unexpected error while performing action.")
        return 130

    return 0

if __name__ == '__main__':
    ret = main(sys.argv)
    logging.shutdown()
    exit(ret)

# vim:tabstop=4:shiftwidth=4:expandtab:spelllang=en_gb:spell:
