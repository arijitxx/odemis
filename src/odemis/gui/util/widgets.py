# -*- coding: utf-8 -*-
"""
Created on 3 Dec 2012

@author: Éric Piel

Copyright © 2012 Éric Piel, Delmic

This file is part of Odemis.

Odemis is free software: you can redistribute it and/or modify it under the terms
of the GNU General Public License version 2 as published by the Free Software
Foundation.

Odemis is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY;
without even the implied warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR
PURPOSE. See the GNU General Public License for more details.

You should have received a copy of the GNU General Public License along with
Odemis. If not, see http://www.gnu.org/licenses/.

"""

import collections
import logging
import math
from odemis.gui.util import call_after_wrapper, call_after, dead_object_wrapper
from odemis.util import units
import time
import wx


def get_all_children(widget, klass=None):
    """ Recursively get all the child widgets of the given widget

    Results can be filtered by providing a class.
    """

    result = []

    for w in widget.GetChildren():
        cl = w.GetChildren()

        if cl:
            result.extend(get_all_children(w, klass))
        elif klass is None:
            result.append(w)
        elif isinstance(w, klass):
            result.append(w)

    return result

def get_sizer_position(window):
    """ Return the int index value of a given window within its containing sizer

    The window must be contained within a BoxSizer
    """
    sizer = window.GetContainingSizer()

    if not sizer or not isinstance(sizer, wx.BoxSizer):
        return None

    for i, sizer_item in enumerate(sizer.GetChildren()):
        if sizer_item.IsWindow() and sizer_item.GetWindow() == window:
            return i

    raise ValueError("Widget not found")


class VigilantAttributeConnector(object):
    """ This class connects a vigilant attribute with a wxPython control,
    making sure that the changes in one are automatically reflected in the
    other.

    At the end of the constructor, the value of the VA is assigned to the
    control!

    """

    def __init__(self, va, value_ctrl, va_2_ctrl=None, ctrl_2_va=None, events=None):
        """
        va (VigilantAttribute): the VA to connect with
        ctrl (wx.Window): a wx widget to connect to
        va_2_ctrl (None or callable ((value) -> None)): a function to be called
            when the VA is updated, to update the widget. If None, try to use
            the default SetValue().
        ctrl_2_va (None or callable ((None) -> value)): a function to be called
            when the widget is updated, to update the VA. If None, try to use
            the default GetValue().
            Can raise ValueError, TypeError or IndexError if data is incorrect
        events (None or wx.EVT_* or tuple of wx.EVT_*): events to bind to update
            the value of the VA
        """
        self.vigilattr = va
        self.value_ctrl = value_ctrl

        # Dead_object_wrapper might need/benefit from recognizing bound methods.
        # Or it can be tough to recognize wxPyDeadObjects being passed as 'self'
        self.va_2_ctrl = call_after_wrapper(dead_object_wrapper(va_2_ctrl or value_ctrl.SetValue))
        self.ctrl_2_va = ctrl_2_va or value_ctrl.GetValue
        if events is None:
            self.change_events = ()
        elif not isinstance(events, collections.Iterable):
            self.change_events = (events,)
        else:
            self.change_events = events

        # Subscribe to the vigilant attribute and initialize
        self._connect(init=True)

    def _on_value_change(self, evt):
        """ This method is called when the value of the control is changed.
        """
        try:
            value = self.ctrl_2_va()
            logging.debug("Assign value %s to vigilant attribute", value)
            self.vigilattr.value = value
        except (ValueError, TypeError, IndexError), exc:
            logging.warn("Illegal value: %s", exc)
            self.va_2_ctrl(self.vigilattr.value)
        finally:
            evt.Skip()

    def pause(self):
        """ Temporarily prevent vigilant attributes from updating controls """
        self.vigilattr.unsubscribe(self.va_2_ctrl)

    def resume(self):
        """ Resume updating controls """
        self.vigilattr.subscribe(self.va_2_ctrl, init=True)

    def _connect(self, init):
        logging.debug("Connecting VigilantAttributeConnector")
        self.vigilattr.subscribe(self.va_2_ctrl, init)
        for event in self.change_events:
            self.value_ctrl.Bind(event, self._on_value_change)

    def disconnect(self):
        logging.debug("Disconnecting VigilantAttributeConnector")
        for event in self.change_events:
            self.value_ctrl.Unbind(event, handler=self._on_value_change)
        self.vigilattr.unsubscribe(self.va_2_ctrl)


class AxisConnector(object):
    """ This class connects the axis of an actuator with a wxPython control,
    making sure that the changes in one are automatically reflected in the
    other.
    """
    def __init__(self, axis, comp, value_ctrl, pos_2_ctrl=None, ctrl_2_pos=None, events=None):
        """
        axis (string): the name of the axis to connect with
        comp (Actuator): the component that contains the axis
        ctrl (wx.Window): a wx widget to connect to
        pos_2_ctrl (None or callable ((value) -> None)): a function to be called
            when the position is updated, to update the widget. If None, try to use
            the default SetValue().
        ctrl_2_pos (None or callable ((None) -> value)): a function to be called
            when the widget is updated, to update the VA. If None, try to use
            the default GetValue().
            Can raise ValueError, TypeError or IndexError if data is incorrect
        events (None or wx.EVT_* or tuple of wx.EVT_*): events to bind to update
            the value of the VA
        """
        self.axis = axis
        self.comp = comp
        self.value_ctrl = value_ctrl
        self.pos_2_ctrl = pos_2_ctrl or value_ctrl.SetValue
        self.ctrl_2_pos = ctrl_2_pos or value_ctrl.GetValue
        if events is None:
            self.change_events = ()
        elif not isinstance(events, collections.Iterable):
            self.change_events = (events,)
        else:
            self.change_events = events

        # Subscribe to the position and initialize
        self._connect(init=True)

    def _on_value_change(self, evt):
        """ This method is called when the value of the control is changed.
        it moves the axis to the new value.
        """
        try:
            value = self.ctrl_2_pos()
            logging.debug("Requesting axis %s to move to %g", self.axis, value)

            # expect absolute move works
            move = {self.axis: value}
            future = self.comp.moveAbs(move)
        except (ValueError, TypeError, IndexError), exc:
            logging.error("Illegal value: %s", exc)
            return
        finally:
            evt.Skip()

        if not future.done():
            # disable the control until the move is finished => gives user
            # feedback and avoids accumulating moves
            self.value_ctrl.Disable()
            future.add_done_callback(self._on_move_done)

    @call_after
    def _on_move_done(self, future):
        """
        Called after the end of a move
        """
        # _on_pos_change() is almost always called as well, but not if the move
        # was so small that the position didn't change. So need to be separate.
        self.value_ctrl.Enable()
        logging.debug("Axis %s finished moving", self.axis)

    @call_after
    def _on_pos_change(self, positions):
        """
        Called when position changes
        """
        position = positions[self.axis]
        logging.debug("Axis has moved to position %g", position)
        self.pos_2_ctrl(position)

    def pause(self):
        """ Temporarily prevent position from updating controls """
        self.comp.position.unsubscribe(self._on_pos_change)

    def resume(self):
        """ Resume updating controls """
        self.comp.position.subscribe(self._on_pos_change, init=True)

    def _connect(self, init):
        logging.debug("Connecting AxisConnector")
        self.comp.position.subscribe(self._on_pos_change, init)
        for event in self.change_events:
            self.value_ctrl.Bind(event, self._on_value_change)

    def disconnect(self):
        logging.debug("Disconnecting AxisConnector")
        for event in self.change_events:
            self.value_ctrl.Unbind(event, self._on_value_change)
        self.comp.position.unsubscribe(self._on_pos_change)


class ProgessiveFutureConnector(object):
    """
    Connects a progressive future to a progress bar
    """
    def __init__(self, future, bar, label=None):
        """
        Update a gauge widget, based on the progress reported by the
        ProgressiveFuture.
        future (ProgressiveFuture)
        bar (gauge): the progress bar widget
        label (TextLabel or None): if given, will also update a the text with
          the time left.
        Note: when the future is complete (done), the progress bar will be set
        to 100%, but the text will not be updated.
        """
        self._future = future
        self._bar = bar
        self._label = label

        # Will contain the info of the future as soon as we get it.
        self._start = None
        self._end = None
        self._prev_left = None

        # a repeating timer, always called in the GUI thread
        self._timer = wx.PyTimer(self._update_progress)
        self._timer.Start(250.0) # 4 Hz

        # Set the progress bar to 0
        bar.Range = 100
        bar.Value = 0

        future.add_update_callback(self._on_progress)
        future.add_done_callback(self._on_done)

    def _on_progress(self, future, past, left):
        """
        Callback called during the acquisition to update on its progress
        past (float): number of s already past
        left (float): estimated number of s left
        """
        now = time.time()
        self._start = now - past
        self._end = now + left

    @call_after
    def _on_done(self, future):
        """
        Called when it's over
        """
        self._timer.Stop()
        if not future.cancelled():
            self._bar.Range = 100
            self._bar.Value = 100

    def _update_progress(self):
        if self._start is None: # no info yet
            return

        now = time.time()
        past = now - self._start
        left = max(0, self._end - now)
        self._prev_left, prev_left = left, self._prev_left

        # progress bar: past / past+left
        can_update = True
        try:
            ratio = past / (past + left)
            # Don't update gauge if ratio reduces
            prev_ratio = self._bar.Value / self._bar.Range
            logging.debug("current ratio %g, old ratio %g", ratio * 100, prev_ratio * 100)
            if (prev_left is not None and
                prev_ratio - 0.1 < ratio < prev_ratio):
                can_update = False
        except ZeroDivisionError:
            pass

        if can_update:
            logging.debug("updating the progress bar to %f/%f", past, past + left)
            self._bar.Range = 100 * (past + left)
            self._bar.Value = 100 * past


        if self._future.done():
            # make really sure we don't update the text after the future is over
            return

        # Time left
        left = math.ceil(left) # pessimistic
        # Avoid back and forth estimation => don't increase unless really huge (> 5s)
        if (prev_left is not None and 0 < left - prev_left < 5):
            logging.debug("No updating progress bar as new estimation is %g s "
                          "while the previous was only %g s",
                          left, prev_left)
            return

        if left > 2:
            lbl_txt = "%s left." % units.readable_time(left)
        else:
            # don't be too precise
            lbl_txt = "a few seconds left."

        if self._label is None:
            self._bar.SetToolTipString(lbl_txt)
        else:
            self._label.SetLabel(lbl_txt)
