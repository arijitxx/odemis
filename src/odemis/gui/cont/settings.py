#-*- coding: utf-8 -*-
"""
@author: Rinze de Laat

Copyright © 2012-2013 Rinze de Laat, Delmic

This file is part of Odemis.

Odemis is free software: you can redistribute it and/or modify it under the
terms of the GNU General Public License version 2 as published by the Free
Software Foundation.

Odemis is distributed in the hope that it will be useful, but WITHOUT ANY
WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS FOR A
PARTICULAR PURPOSE. See the GNU General Public License for more details.

You should have received a copy of the GNU General Public License along with
Odemis. If not, see http://www.gnu.org/licenses/.


### Purpose ###

This module contains classes to control the settings controls in the right
setting column of the user interface.

"""

from __future__ import division

from abc import ABCMeta
import collections
import logging
import numbers
from odemis import model, util
import odemis.dataio
from odemis.gui.comp.combo import ComboBox
from odemis.gui.comp.file import EVT_FILE_SELECT
from odemis.gui.comp.slider import UnitFloatSlider
from odemis.gui.conf.settingspanel import CONFIG, CONFIG_PER_ROLE
import odemis.gui.util
from odemis.gui.util.widgets import VigilantAttributeConnector, AxisConnector
from odemis.model import getVAs, NotApplicableError, VigilantAttributeBase
from odemis.util.driver import reproduceTypedValue
from odemis.util.units import readable_str
import re
import time
import wx
from wx.lib.pubsub import pub

import odemis.gui.comp.hist as hist
from odemis.gui.comp.settings import SettingsPanel
import odemis.gui.conf as guiconf
import odemis.util.units as utun


####### Utility functions #######
def choice_to_str(choice):
    if not isinstance(choice, collections.Iterable):
        choice = [unicode(choice)]
    return u" x ".join([unicode(c) for c in choice])


def label_to_human(camel_label):
    """ Converts a camel-case label into a human readable one """
    # add space after each upper case
    # then, make the first letter uppercase and all the other ones lowercase
    return re.sub(r"([A-Z])", r" \1", camel_label).capitalize()


def bind_menu(se):
    """ Add a menu to reset a setting entry to the original (current) value

    .. note:
        `se` must at least have a valid label, ctrl and va

    :param se: (SettingEntry)

    """

    orig_val = se.va.value

    def reset_value(evt):
        se.va.value = orig_val
        wx.CallAfter(pub.sendMessage, 'setting.changed', setting_ctrl=se.value_ctrl)

    def show_reset_menu(evt):
        # No menu needed if value hasn't changed
        if se.va.value == orig_val:
            return  # TODO: or display it greyed out?

        menu = wx.Menu()
        mi = wx.MenuItem(menu, wx.NewId(), 'Reset value')

        eo = evt.GetEventObject()
        eo.Bind(wx.EVT_MENU, reset_value, mi)

        menu.AppendItem(mi)
        eo.PopupMenu(menu)

    se.value_ctrl.Bind(wx.EVT_CONTEXT_MENU, show_reset_menu)
    se.lbl_ctrl.Bind(wx.EVT_CONTEXT_MENU, show_reset_menu)


####### Classes #######

class Entry(object):

    def __init__(self, name, comp, lbl_ctrl, value_ctrl):
        self.name = name
        self.comp = comp
        self.lbl_ctrl = lbl_ctrl
        self.value_ctrl = value_ctrl

    def __repr__(self):
        return "Label: %s" % self.lbl_ctrl.GetLabel() if self.lbl_ctrl else None

    @property
    def va(self):
        """ Added for quick & dirty backwards compatibility. Can/should be replaced """
        if hasattr(self, 'vigilattr'):
            return self.vigilattr
        return None

    def highlight(self, active=True):
        """ Highlight the setting entry by adjusting its colour

        active (boolean): whether it should be highlighted or not

        """

        if not self.lbl_ctrl:
            return

        if active:
            self.lbl_ctrl.SetForegroundColour(odemis.gui.FG_COLOUR_HIGHLIGHT)
        else:
            self.lbl_ctrl.SetForegroundColour(odemis.gui.FG_COLOUR_MAIN)


class SettingEntry(VigilantAttributeConnector, Entry):

    def __init__(self, name, va=None, comp=None, lbl_ctrl=None, value_ctrl=None,
                 va_2_ctrl=None, ctrl_2_va=None, events=None):
        """
        :param name: (str): The name of the setting
        :param va: (VA): The VigilantAttribute associated with the setting
        :param comp: (HardwareComponent): The component to which the setting belongs
        :param lbl_ctrl: (wx.StaticText): The setting label
        :param value_ctrl: (wx.Window): The widget containing the current value

        See the VigilantAttributeConnector class for a description of the other parameters.

        """

        Entry.__init__(self, name, comp, lbl_ctrl, value_ctrl)

        if None not in (va, value_ctrl):
            super(SettingEntry, self).__init__(va, value_ctrl, va_2_ctrl, ctrl_2_va, events)
        elif any([va_2_ctrl, ctrl_2_va, events]):
            logging.error("Cannot create VigilantAttributeConnector")
        else:
            logging.debug("Cannot create VigilantAttributeConnector")


class AxisSettingEntry(AxisConnector, Entry):

    def __init__(self, name, comp, lbl_ctrl=None, value_ctrl=None,
                 pos_2_ctrl=None, ctrl_2_pos=None, events=None):
        """
        :param name: (str): The name of the setting
        :param comp: (HardwareComponent): The component to which the setting belongs
        :param lbl_ctrl: (wx.StaticText): The setting label
        :param value_ctrl: (wx.Window): The widget containing the current value

        See the AxisConnector class for a description of the other parameters.

        """

        Entry.__init__(self, name, comp, lbl_ctrl, value_ctrl)

        if None not in (name, value_ctrl):
            super(AxisSettingEntry, self).__init__(name, comp, value_ctrl,
                                                   pos_2_ctrl, ctrl_2_pos, events)
        elif any([pos_2_ctrl, ctrl_2_pos, events]):
            logging.error("Cannot create AxisConnector")
        else:
            logging.debug("Cannot create AxisConnector")


class SettingsController(object):
    """ Settings base class which describes an indirect wrapper for
    FoldPanelItems.

    :param fold_panel: (FoldPanelItem) Parent window
    :param default_msg: (str) Text message which will be shown if the
        SettingPanel does not contain any child windows.
    :param highlight_change: (bool) If set to True, the values will be
        highlighted when they match the cached values.
    NOTE: Do not instantiate this class, but always inherit it.
    """

    __metaclass__ = ABCMeta

    def __init__(self, fold_panel, default_msg, highlight_change=False):

        self.panel = SettingsPanel(fold_panel, default_msg=default_msg)
        fold_panel.add_item(self.panel)

        self.highlight_change = highlight_change
        self.num_entries = 0
        self.entries = []  # list of SettingEntry

    def hide_panel(self):
        self.show_panel(False)

    def show_panel(self, show=True):
        self.panel.Show(show)

    def pause(self):
        """ Pause SettingEntry related control updates """
        for entry in self.entries:
            if hasattr(entry, 'vigilattr') and entry.vigilattr:
                entry.pause()

    def resume(self):
        """ Pause SettingEntry related control updates """
        for entry in self.entries:
            if hasattr(entry, 'vigilattr') and entry.vigilattr:
                entry.resume()

    def enable(self, enabled):
        for entry in self.entries:
            if entry.value_ctrl:
                entry.value_ctrl.Enable(enabled)

    @staticmethod
    def _determine_default_control(va):
        """ Determine the default control to use to represent a vigilant attribute

        :param va: (VigilantAttribute)

        return (odemis.gui.CONTROL_*)

        """

        if not va:
            logging.warn("No VA provided!")
            return odemis.gui.CONTROL_NONE

        if va.readonly:
            # Uncomment this line to hide Read only VAs by default
            # return odemis.gui.CONTROL_NONE
            return odemis.gui.CONTROL_READONLY
        else:
            try:
                # This statement will raise an exception when no choices are present
                logging.debug("found choices %s", va.choices)

                max_num_choices = 5
                max_value_len = 5

                # If there are too many choices, or their values are too long
                # in string representation, use a drop-down box

                choices_str = "".join([str(c) for c in va.choices])
                if len(va.choices) <= 1:
                    # not much choices really
                    return odemis.gui.CONTROL_READONLY
                elif (len(va.choices) < max_num_choices and
                      len(choices_str) < max_num_choices * max_value_len):
                    return odemis.gui.CONTROL_RADIO
                else:
                    return odemis.gui.CONTROL_COMBO
            except (AttributeError, NotApplicableError):
                pass

            try:
                # An exception will be raised if no range attribute is found
                logging.debug("found range %s", va.range)

                # TODO: if unit is "s" => scale=exp
                if isinstance(va.value, (int, long, float)):
                    return odemis.gui.CONTROL_SLIDER
            except (AttributeError, NotApplicableError):
                pass

            # Return default control
            return odemis.gui.CONTROL_TEXT

    @staticmethod
    def _get_va_meta(comp, va, conf):
        """ Retrieve the range and choices values from the vigilant attribute
        or override them with the values provided in the configuration.

        """

        r = conf.get("range", (None, None))
        minv, maxv = (None, None)

        try:
            if callable(r):
                minv, maxv = r(comp, va, conf)
            elif r == (None, None):
                minv, maxv = va.range
            else:
                # Intersect the two ranges
                # TODO: handle iterables
                minv, maxv = r
                minv, maxv = max(minv, va.range[0]), min(maxv, va.range[1])
        except (AttributeError, NotApplicableError):
            pass

        # Ensure the range encompasses the current value
        if None not in (minv, maxv):
            val = va.value
            if isinstance(val, numbers.Real):
                minv, maxv = min(minv, val), max(maxv, val)

        choices = conf.get("choices", None)
        try:
            if callable(choices):
                choices = choices(comp, va, conf)
            elif choices is None:
                choices = va.choices
            elif hasattr(va, "choices") and isinstance(va.choices, collections.Mapping):
                # Intersect the two choice sets
                choices &= va.choices
            elif hasattr(va, "range") and isinstance(va.range, collections.Iterable):
                # Ensure that each choice is within the range
                rng = va.range
                choices = set(c for c in choices if rng[0] <= c <= rng[1])
        except (AttributeError, NotApplicableError):
            pass

        # Get unit from config, vigilant attribute or use an empty one
        unit = conf.get('unit', va.unit or "")

        return minv, maxv, choices, unit

    def add_browse_button(self, label, label_tl=None, clearlabel=None):
        config = guiconf.get_acqui_conf()
        lbl_ctrl, value_ctrl = self.panel.add_file_button(label, config.last_path, clearlabel)

        lbl_ctrl.SetToolTipString(label_tl)
        value_ctrl.SetToolTipString(label_tl)

        # Add the corresponding setting entry
        ne = SettingEntry(name=label, lbl_ctrl=lbl_ctrl, value_ctrl=value_ctrl)
        self.entries.append(ne)
        return ne

    def _get_number_formatter(self, value_ctrl, val, val_unit):
        """ TODO: replace/refactor. This method was added as a quick fix """
        value_formatter = None

        if (
                isinstance(val, (int, long, float)) or
                (
                    isinstance(val, collections.Iterable) and
                    len(val) > 0 and
                    isinstance(val[0], (int, long, float))
                )
        ):
            def value_formatter(value, unit=val_unit):
                value_ctrl.SetValue(readable_str(value, unit, sig=3))

        return value_formatter

    def add_value(self, name, vigil_attr, comp, conf=None):
        """ Add a name/value pair to the settings panel.

        :param name: (string): name of the value
        :param vigil_attr: (VigilantAttribute)
        :param comp: (Component): the component that contains this VigilantAttribute
        :param conf: ({}): Configuration items that may override default settings
        """
        assert isinstance(vigil_attr, VigilantAttributeBase)

        # Remove any 'empty panel' warning
        self.panel.clear_default_message()

        # If no conf provided, set it to an empty dictionary
        conf = conf or {}

        # Get the range and choices
        min_val, max_val, choices, unit = self._get_va_meta(comp, vigil_attr, conf)
        ctrl_format = conf.get("format", True)
        prefix = None

        if choices:
            # choice_fmt is an iterable of tuples: choice -> formatted choice
            # (like a dict, but keeps order)
            if isinstance(choices, dict):
                # it's then already value -> string (user-friendly display)
                choices_fmt = choices.items()
            elif (ctrl_format and len(choices) > 1 and
                  all([isinstance(c, numbers.Real) for c in choices])):
                # Try to share the same unit prefix, if the range is not too big
                choices_abs = set(abs(c) for c in choices)
                # 0 doesn't affect the unit prefix but is annoying for divisions
                choices_abs.discard(0)
                mn, mx = min(choices_abs), max(choices_abs)
                if mx / mn > 1000:
                    # TODO: use readable_str(c, unit, sig=3)? is it more readable?
                    # => need to not add prefix+units from the combo box
                    # (but still handle differently for radio)
                    choices_fmt = [(c, choice_to_str(c)) for c in choices]
                else:
                    fmt, prefix = utun.si_scale_list(choices)
                    choices_fmt = zip(choices, [u"%g" % c for c in fmt])
            else:
                choices_fmt = [(c, choice_to_str(c)) for c in choices]

            choices_fmt = sorted(choices_fmt)  # sort 2-tuples = according to first value in tuple

        # Get the defined type of control or assign a default one
        try:
            control_type = conf['control_type']
            if callable(control_type):
                control_type = control_type(comp, vigil_attr, conf)
            # read-only takes precedence (unless it was requested to hide it)
            if vigil_attr.readonly and control_type != odemis.gui.CONTROL_NONE:
                control_type = odemis.gui.CONTROL_READONLY
        except KeyError:
            control_type = self._determine_default_control(vigil_attr)

        # Change radio type to fitting type depending on its content
        if control_type == odemis.gui.CONTROL_RADIO:
            if len(choices_fmt) <= 1:  # only one choice => force label
                control_type = odemis.gui.CONTROL_READONLY
            elif len(choices_fmt) > 10:  # too many choices => combo
                control_type = odemis.gui.CONTROL_COMBO
            else:
                # choices names too long => combo
                max_len = max([len(f) for _, f in choices_fmt])
                if max_len > 6:
                    control_type = odemis.gui.CONTROL_COMBO

        # Special case, early stop
        if control_type == odemis.gui.CONTROL_NONE:
            # No value, not even label
            # Just an empty entry, so that the settings are saved during acquisition
            ne = SettingEntry(name=name, va=vigil_attr, comp=comp)
            self.entries.append(ne)
            # don't increase panel.num_rows, as it doesn't add any graphical element
            return

        # Format label
        label_text = conf.get('label', label_to_human(name))
        tooltip = conf.get('tooltip', "")

        logging.debug("Adding VA %s", label_text)
        # Create the needed wxPython controls
        if control_type == odemis.gui.CONTROL_READONLY:
            val = vigil_attr.value  # only format if it's a number
            lbl_ctrl, value_ctrl = self.panel.add_readonly_field(label_text, val)
            value_formatter = self._get_number_formatter(value_ctrl, val, unit)
            ne = SettingEntry(name=name, va=vigil_attr, comp=comp,
                              lbl_ctrl=lbl_ctrl, value_ctrl=value_ctrl,
                              va_2_ctrl=value_formatter)

        elif control_type == odemis.gui.CONTROL_TEXT:
            val = vigil_attr.value  # only format if it's a number
            lbl_ctrl, value_ctrl = self.panel.add_text_field(label_text, val)
            value_formatter = self._get_number_formatter(value_ctrl, val, unit)
            ne = SettingEntry(name=name, va=vigil_attr, comp=comp,
                              lbl_ctrl=lbl_ctrl, value_ctrl=value_ctrl,
                              va_2_ctrl=value_formatter)

        elif control_type == odemis.gui.CONTROL_SLIDER:
            # The slider is accompanied by an extra number text field

            if "type" in conf:
                if conf["type"] == "integer":
                    # add_integer_slider
                    factory = self.panel.add_integer_slider
                else:
                    factory = self.panel.add_float_slider
            else:
                # guess from value(s)
                known_values = [vigil_attr.value, min_val, max_val]
                if choices is not None:
                    known_values.extend(list(choices))
                if any(isinstance(v, float) for v in known_values):
                    factory = self.panel.add_float_slider
                else:
                    factory = self.panel.add_integer_slider

            # The event configuration determines what event will signal that the setting entry
            # has changed value.
            if "event" in conf:
                if conf["event"] == wx.EVT_SCROLL_CHANGED:
                    update_event = conf["event"]
                else:
                    raise ValueError("Illegal event type for Slider setting entry!")
            else:
                # This event type will make the value update continuously as the slider is dragged
                update_event = wx.EVT_SLIDER

            ctrl_conf = {
                'min_val': min_val,
                'max_val': max_val,
                'scale': conf.get('scale', None),
                'unit': unit,
                't_size': (50, -1),
                'accuracy': conf.get('accuracy', 4),
                }

            lbl_ctrl, value_ctrl = factory(label_text, vigil_attr.value, ctrl_conf)

            ne = SettingEntry(name=name, va=vigil_attr, comp=comp,
                              lbl_ctrl=lbl_ctrl, value_ctrl=value_ctrl,
                              events=update_event)

            # TODO: deprecated?
            value_ctrl.Bind(wx.EVT_SLIDER, self.on_setting_changed)

        elif control_type == odemis.gui.CONTROL_INT:
            if unit == "":  # don't display unit prefix if no unit
                unit = None

            ctrl_conf = {
                'min_val': min_val,
                'max_val': max_val,
                'unit': unit,
                'choices': choices,
            }

            lbl_ctrl, value_ctrl = self.panel.add_int_field(label_text, conf=ctrl_conf)

            ne = SettingEntry(name=name, va=vigil_attr, comp=comp,
                              lbl_ctrl=lbl_ctrl, value_ctrl=value_ctrl,
                              events=wx.EVT_COMMAND_ENTER)

            value_ctrl.Bind(wx.EVT_COMMAND_ENTER, self.on_setting_changed)

        elif control_type == odemis.gui.CONTROL_FLT:
            if unit == "": # don't display unit prefix if no unit
                unit = None

            ctrl_conf = {
                'min_val': min_val,
                'max_val': max_val,
                'unit': unit,
                'choices': choices,
                'accuracy': conf.get('accuracy', 5),
            }

            lbl_ctrl, value_ctrl = self.panel.add_float_field(label_text, conf=ctrl_conf)

            ne = SettingEntry(name=name, va=vigil_attr, comp=comp,
                              lbl_ctrl=lbl_ctrl, value_ctrl=value_ctrl,
                              events=wx.EVT_COMMAND_ENTER)

            value_ctrl.Bind(wx.EVT_COMMAND_ENTER, self.on_setting_changed)

        elif control_type == odemis.gui.CONTROL_RADIO:
            unit_fmt = (prefix or "") + (unit or "")

            ctrl_conf = {
                'size': (-1, 16),
                'units': unit_fmt,
                'choices': [v for v, _ in choices_fmt],
                'labels': [l for _, l in choices_fmt],
            }

            lbl_ctrl, value_ctrl = self.panel.add_radio_control(label_text, conf=ctrl_conf)

            if conf.get('type', None) == "1d_binning":
                # need to convert back and forth between 1D and 2D
                # from 2D to 1D (just pick X)
                def radio_set(value, ctrl=value_ctrl):
                    v = value[0]
                    logging.debug("Setting Radio value to %d", v)
                    # it's fine to set a value not in the choices, it will
                    # just not set any of the buttons.
                    return ctrl.SetValue(v)

                # from 1D to 2D (both identical)
                def radio_get(ctrl=value_ctrl):
                    value = ctrl.GetValue()
                    return (value, value)
            elif conf.get('type', None) == "1std_binning":
                # need to convert back and forth between 1D and 2D
                # from 2D to 1D (just pick X)
                def radio_set(value, ctrl=value_ctrl):
                    v = value[0]
                    logging.debug("Setting Radio value to %d", v)
                    # it's fine to set a value not in the choices, it will
                    # just not set any of the buttons.
                    return ctrl.SetValue(v)

                # from 1D to 2D (don't change dimensions >1)
                def radio_get(ctrl=value_ctrl, va=vigil_attr):
                    value = ctrl.GetValue()
                    new_val = list(va.value)
                    new_val[0] = value
                    return new_val
            else:
                radio_get = None
                radio_set = None

            ne = SettingEntry(name=name, va=vigil_attr, comp=comp,
                              lbl_ctrl=lbl_ctrl, value_ctrl=value_ctrl,
                              va_2_ctrl=radio_set, ctrl_2_va=radio_get, events=wx.EVT_BUTTON)

            value_ctrl.Bind(wx.EVT_BUTTON, self.on_setting_changed)

        elif control_type == odemis.gui.CONTROL_COMBO:

            ctrl_conf = {

            }

            # TODO: Might need size=(100, 16)!!
            lbl_ctrl, value_ctrl = self.panel.add_combobox_control(label_text, '', ctrl_conf)

            # Set choices
            for choice, formatted in choices_fmt:
                value_ctrl.Append(u"%s %s" % (formatted, (prefix or "") + unit), choice)

            # A small wrapper function makes sure that the value can
            # be set by passing the actual value (As opposed to the text label)
            def cb_set(value, ctrl=value_ctrl, u=unit):
                for i in range(ctrl.Count):
                    if ctrl.GetClientData(i) == value:
                        logging.debug("Setting ComboBox value to %s", ctrl.Items[i])
                        ctrl.SetSelection(i)
                        # Note: with wxpython < 3.0, use:
                        # ctrl.SetValue(ctrl.Items[i])
                        break
                else:
                    logging.debug("No existing label found for value %s", value)
                    # entering value as free text
                    txt = readable_str(value, u, sig=3)
                    return ctrl.SetValue(txt)

            # equivalent wrapper function to retrieve the actual value
            def cb_get(ctrl=value_ctrl, va=vigil_attr):
                value = ctrl.GetValue()
                # Try to use the predefined value if it's available
                i = ctrl.GetSelection()

                # Note: with wxpython < 3.0, use:
                # for i in range(ctrl.Count):
                # Warning: if the text contains an unknown value, GetSelection will
                # not return wx.NOT_FOUND (as expected), but the last selection value
                if i != wx.NOT_FOUND and ctrl.Items[i] == value:
                    logging.debug("Getting CB value %s", ctrl.GetClientData(i))
                    return ctrl.GetClientData(i)
                else:
                    logging.debug("Trying to parse CB free value %s", value)
                    cur_val = va.value
                    # Try to find a good corresponding value inside the string
                    new_val = reproduceTypedValue(cur_val, value)
                    if isinstance(new_val, collections.Iterable):
                        # be less picky, by shortening the number of values if it's too many
                        new_val = new_val[:len(cur_val)]

                    # if it ends up being the same value as before the CB will
                    # not update, so force it now
                    if cur_val == new_val:
                        cb_set(cur_val)
                    return new_val

            ne = SettingEntry(name=name, va=vigil_attr, comp=comp,
                              lbl_ctrl=lbl_ctrl, value_ctrl=value_ctrl,
                              va_2_ctrl=cb_set, ctrl_2_va=cb_get, events=(wx.EVT_COMBOBOX,
                                                                          wx.EVT_TEXT_ENTER))

            value_ctrl.Bind(wx.EVT_COMBOBOX, self.on_setting_changed)
            value_ctrl.Bind(wx.EVT_TEXT_ENTER, self.on_setting_changed)

        else:
            logging.error("Unknown control type %s", control_type)

        value_ctrl.SetToolTipString(tooltip)
        lbl_ctrl.SetToolTipString(tooltip)

        self.entries.append(ne)

        if self.highlight_change:
            bind_menu(ne)

        self.panel.Parent.Parent.Layout()

        return ne

    def add_axis(self, name, comp, conf=None):
        """
        Add a widget to the setting panel to control an axis

        :param name: (string): name of the axis
        :param comp: (Component): the component that contains this axis
        :param conf: ({}): Configuration items that may override default settings
        """
        # If no conf provided, set it to an empty dictionary
        conf = conf or {}

        # Format label
        label = conf.get('label', label_to_human(name))
        # Add the label to the panel
        lbl_ctrl = wx.StaticText(self.panel, -1, u"%s" % label)
        self.panel._gb_sizer.Add(lbl_ctrl, (self.panel.num_rows, 0),
                           flag=wx.ALL | wx.ALIGN_CENTER_VERTICAL, border=5)

        logging.debug("Adding Axis control %s", label)

        ad = comp.axes[name]
        pos = comp.position.value[name]
        unit = ad.unit

        # If axis has .range (continuous) => slider
        # If axis has .choices (enumerated) => combo box
        if hasattr(ad, "range"):
            minv, maxv = ad.range

            value_ctrl = UnitFloatSlider(
                self.panel,
                value=pos,
                min_val=minv,
                max_val=maxv,
                unit=unit,
                t_size=(50, -1),
                accuracy=conf.get('accuracy', 3)
            )

            # don't bind to wx.EVT_SLIDER, which happens as soon as the slider moves,
            # but to EVT_SCROLL_CHANGED, which happens when the user has made his
            # mind. This avoid too many unnecessary actuator moves and disabling the
            # widget too early.
            ne = AxisSettingEntry(name, comp, lbl_ctrl=lbl_ctrl, value_ctrl=value_ctrl,
                                  events=wx.EVT_SCROLL_CHANGED)
        else:
            # format the choices
            choices = ad.choices
            if isinstance(choices, dict):
                # it's then already value -> string (user-friendly display)
                choices_fmt = choices.items()
            elif (unit and len(choices) > 1 and
                  all([isinstance(c, numbers.Real) for c in choices])):
                # TODO: need same update as add_value
                fmt, prefix = utun.si_scale_list(choices)
                choices_fmt = zip(choices, [u"%g" % c for c in fmt])
                unit = prefix + unit
            else:
                choices_fmt = [(c, choice_to_str(c)) for c in choices]

            choices_fmt = sorted(choices_fmt) # sort 2-tuples = according to first value in tuple

            value_ctrl = ComboBox(
                self.panel,
                wx.ID_ANY,
                value='', pos=(0, 0), size=(100, 16),
                # FIXME: should be readonly, but it fails with GetInsertionPoint
                style=wx.BORDER_NONE | wx.TE_PROCESS_ENTER | wx.CB_READONLY
            )

            def _eat_event(evt):
                """ Quick and dirty empty function used to 'eat'
                mouse wheel events
                """
                pass
            value_ctrl.Bind(wx.EVT_MOUSEWHEEL, _eat_event)

            # Set choices
            if unit is None:
                unit = ""
            for choice, formatted in choices_fmt:
                value_ctrl.Append(u"%s %s" % (formatted, unit), choice)

            # A small wrapper function makes sure that the value can
            # be set by passing the actual value (As opposed to the text label)
            def cb_set(value, ctrl=value_ctrl, unit=unit):
                for i in range(ctrl.Count):
                    if ctrl.GetClientData(i) == value:
                        logging.debug("Setting ComboBox value to %s", ctrl.Items[i])
                        return ctrl.SetValue(ctrl.Items[i])
                else:
                    logging.warning("No existing label found for value %s", value)
                    return ctrl.GetValue()

            # equivalent wrapper function to retrieve the actual value
            def cb_get(ctrl=value_ctrl, name=name):
                value = ctrl.GetValue()
                # Try to use the predefined value if it's available
                for i in range(ctrl.Count):
                    if ctrl.Items[i] == value:
                        logging.debug("Getting CB value %s", ctrl.GetClientData(i))
                        return ctrl.GetClientData(i)
                else:
                    logging.error("Failed to find value %s for axis %s", value, name)

            ne = AxisSettingEntry(name, comp, lbl_ctrl=lbl_ctrl, value_ctrl=value_ctrl,
                                  pos_2_ctrl=cb_set, ctrl_2_pos=cb_get,
                                  events=(wx.EVT_COMBOBOX, wx.EVT_TEXT_ENTER))

        self.panel._gb_sizer.Add(value_ctrl, (self.panel.num_rows, 1),
                                 flag=wx.ALL | wx.EXPAND | wx.ALIGN_CENTER_VERTICAL,
                                 border=5)

        self.entries.append(ne)
        self.panel.num_rows += 1

        if self.highlight_change:
            bind_menu(ne)

        self.panel.Parent.Parent.Layout()

    def add_widgets(self, *wdg):
        """
        Adds a widget at the end of the panel, on the whole width
        wdg (wxWindow): the widgets to add (max 2)
        """
        # if only one widget: span over all the panel width
        if len(wdg) == 1:
            span = (1, 2)
        else:
            span = wx.DefaultSpan

        for i, w in enumerate(wdg):
            self.panel._gb_sizer.Add(w, (self.panel.num_rows, i), span=span,
                               flag=wx.ALL | wx.EXPAND,
                               border=5)
        self.panel.num_rows += 1

    def add_metadata(self, key, value):
        """
        Adds an entry representing specific metadata. According to the
         metadata key, the right representation is used for the value.
        key (model.MD_*): the metadata key
        value (depends on the metadata): the value to display
        """
        # By default the key is a nice user-readable string
        label = unicode(key)

        # Convert value to a nice string according to the metadata type
        try:
            if key == model.MD_ACQ_DATE:
                # convert to a date using the user's preferences
                nice_str = time.strftime(u"%c", time.localtime(value))
            else:
                # Still try to beautify a bit if it's a number
                if (isinstance(value, (int, long, float)) or
                    (isinstance(value, collections.Iterable) and len(value) > 0
                      and isinstance(value[0], (int, long, float)))
                    ):
                    nice_str = readable_str(value, sig=3)
                else:
                    nice_str = unicode(value)
        except Exception:
            logging.exception("Trying to convert metadata %s", key)
            nice_str = "N/A"

        self.panel.add_readonly_field(label, nice_str)

    def on_setting_changed(self, evt):
        logging.debug("Setting has changed")
        evt_obj = evt.GetEventObject()
        # Make sure the message is sent form the main thread
        wx.CallAfter(pub.sendMessage, 'setting.changed', setting_ctrl=evt_obj)
        evt.Skip()

    def Refresh(self):
        self.panel.Layout()

        p = self.panel.Parent
        while p:
            if isinstance(p, wx.ScrolledWindow):
                p.FitInside()
                p = None
            else:
                p = p.Parent


class SemSettingsController(SettingsController):
    pass


class OpticalSettingsController(SettingsController):
    pass


class AngularSettingsController(SettingsController):
    pass


class SpectrumSettingsController(SettingsController):
    pass


class FileInfoSettingsController(SettingsController):
    pass


class SettingsBarController(object):
    """ The main controller class for the settings panel in the live view and acquisition frame

    This class can be used to set, get and otherwise manipulate the content of the setting panel.

    """

    def __init__(self, tab_data, highlight_change=False):
        self._tab_data_model = tab_data
        self.settings_panels = []

        # TODO: see if we need to listen to main.is_acquiring, and automatically
        # pause + enable. For now, it's done by the acquisition controllers,
        # and it avoids pausing the settings controllers from other tabs.

        # build the default config value based on the global one + the role
        self._va_config = CONFIG.copy()
        if tab_data.main.role in CONFIG_PER_ROLE:
            util.rec_update(self._va_config, CONFIG_PER_ROLE[tab_data.main.role])

    def pause(self):
        """ Pause SettingEntry related control updates """
        for panel in self.settings_panels:
            panel.pause()

    def resume(self):
        """ Resume SettingEntry related control updates """
        for panel in self.settings_panels:
            panel.resume()

    @property
    def entries(self):
        """ Return a list of all the setting entries of all the panels """
        entries = []
        for panel in self.settings_panels:
            entries.extend(panel.entries)
        return entries

    def enable(self, enabled):
        for panel in self.settings_panels:
            panel.enable(enabled)

    # VAs which should never be displayed
    HIDDEN_VAS = {"children", "affects", "state"}
    def add_component(self, label, comp, panel):

        self.settings_panels.append(panel)

        try:
            name = "Name"  # for exception handling only
            # We no longer display the component name
            # panel.add_label(label, comp.name, selectable=False)
            vigil_attrs = getVAs(comp)
            for name, value in vigil_attrs.items():
                if name in self.HIDDEN_VAS:
                    continue
                if comp.role in self._va_config and name in self._va_config[comp.role]:
                    conf = self._va_config[comp.role][name]
                else:
                    logging.info("No config found for %s: %s", comp.role, name)
                    conf = None
                panel.add_value(name, value, comp, conf)
        except TypeError:
            msg = "Error adding %s setting for: %s"
            logging.exception(msg, comp.name, name)

    def add_stream(self, stream):
        pass


class SecomSettingsController(SettingsBarController):

    def __init__(self, parent_frame, tab_data, highlight_change=False):
        super(SecomSettingsController, self).__init__(tab_data,
                                                      highlight_change)
        main_data = tab_data.main

        self._sem_panel = SemSettingsController(
                                    parent_frame.fp_settings_secom_sem,
                                    "No SEM found",
                                    highlight_change)

        self._optical_panel = OpticalSettingsController(
                                    parent_frame.fp_settings_secom_optical,
                                    "No optical microscope found",
                                    highlight_change)

        # Query Odemis daemon (Should move this to separate thread)
        if main_data.ccd:
            self.add_component("Camera",
                                main_data.ccd,
                                self._optical_panel)

            if main_data.light:
                self._optical_panel.panel.add_divider()

                self._optical_panel.add_value(
                                        "power",
                                        main_data.light.power,
                                        main_data.light,
                                        self._va_config["light"]["power"]
                                        )

        if main_data.ebeam:
            self.add_component("SEM", main_data.ebeam, self._sem_panel)


class LensAlignSettingsController(SettingsBarController):

    def __init__(self, parent_frame, tab_data, highlight_change=False):
        super(LensAlignSettingsController, self).__init__(tab_data,
                                                          highlight_change)
        main_data = tab_data.main

        self._sem_panel = SemSettingsController(
                                    parent_frame.fp_lens_sem_settings,
                                    "No SEM found",
                                    highlight_change)

        self._optical_panel = OpticalSettingsController(
                                    parent_frame.fp_lens_opt_settings,
                                    "No optical microscope found",
                                    highlight_change)

        # Query Odemis daemon (Should move this to separate thread)
        if main_data.ccd:
            self.add_component("Camera",
                                main_data.ccd,
                                self._optical_panel)

        # TODO: allow to change light.power

        if main_data.ebeam:
            self.add_component("SEM", main_data.ebeam, self._sem_panel)

class SparcSettingsController(SettingsBarController):

    def __init__(self, parent_frame, tab_data, highlight_change=False,
                 spec_stream=None, ar_stream=None):
        super(SparcSettingsController, self).__init__(tab_data,
                                                      highlight_change)
        main_data = tab_data.main

        self._sem_panel = SemSettingsController(
            parent_frame.fp_settings_sparc_sem,
            "No SEM found",
            highlight_change
        )
        self._angular_panel = AngularSettingsController(
            parent_frame.fp_settings_sparc_angular,
            "No angular camera found",
            highlight_change
        )
        self._spectrum_panel = SpectrumSettingsController(
            parent_frame.fp_settings_sparc_spectrum,
            "No spectrometer found",
            highlight_change
        )

        # Somewhat of a hack to get direct references to a couple of controls
        self.angular_rep_ent = None
        self.spectro_rep_ent = None
        self.spec_pxs_ent = None

        if main_data.ebeam:
            self.add_component(
                "SEM",
                main_data.ebeam,
                self._sem_panel
            )

        if main_data.spectrometer:
            self.add_component(
                "Spectrometer",
                main_data.spectrometer,
                self._spectrum_panel
            )
            # If available, add filter selection
            # TODO: have the control in a (common) separate panel?
            # TODO: also add it to the Mirror alignment tab?
            if main_data.light_filter:
                self._spectrum_panel.add_axis("band", main_data.light_filter,
                                              self._va_config["filter"]["band"])

            self._spectrum_panel.panel.add_divider()
            if spec_stream:
                self.spectro_rep_ent = self._spectrum_panel.add_value(
                    "repetition",
                    spec_stream.repetition,
                    None,  #component
                    self._va_config["streamspec"]["repetition"]
                )
                spec_stream.repetition.subscribe(self.on_spec_rep)

                self.spec_pxs_ent = self._spectrum_panel.add_value(
                    "pixelSize",
                    spec_stream.pixelSize,
                    None,  #component
                    self._va_config["streamspec"]["pixelSize"]
                )
            else:
                logging.warning("Spectrometer available, but no spectrum "
                                "stream provided")


            # Add spectrograph control if available
            if main_data.spectrograph:
                # Without the "wavelength" axis, it's boring
                if "wavelength" in main_data.spectrograph.axes:
                    self._spectrum_panel.add_axis(
                        "wavelength",
                        main_data.spectrograph,
                        self._va_config["spectrograph"]["wavelength"])
                if "grating" in main_data.spectrograph.axes:
                    self._spectrum_panel.add_axis(
                        "grating",
                        main_data.spectrograph,
                        self._va_config["spectrograph"]["grating"])

            # Add a intensity/time graph
            self.spec_graph = hist.Histogram(self._spectrum_panel.panel,
                                        size=(-1, 40))
            self.spec_graph.SetBackgroundColour("#000000")
            self._spectrum_panel.add_widgets(self.spec_graph)
            # the "Mean" value bellow the graph
            lbl_mean = wx.StaticText(self._spectrum_panel.panel, label="Mean")
            tooltip_txt = "Average intensity value of the last image"
            lbl_mean.SetToolTipString(tooltip_txt)
            self.txt_mean = wx.TextCtrl(self._spectrum_panel.panel, style=wx.BORDER_NONE | wx.TE_READONLY)
            self.txt_mean.SetForegroundColour(odemis.gui.FG_COLOUR_DIS)
            self.txt_mean.SetBackgroundColour(odemis.gui.BG_COLOUR_MAIN)
            self.txt_mean.SetToolTipString(tooltip_txt)
            self._spectrum_panel.add_widgets(lbl_mean, self.txt_mean)

        else:
            parent_frame.fp_settings_sparc_spectrum.Hide()

        if main_data.ccd:
            self.add_component("Camera", main_data.ccd, self._angular_panel)

            if main_data.light_filter:
                self._angular_panel.add_axis("band", main_data.light_filter,
                                             self._va_config["filter"]["band"])

            self._angular_panel.panel.add_divider()
            if ar_stream is not None:
                self.angular_rep_ent = self._angular_panel.add_value(
                    "repetition",
                    ar_stream.repetition,
                    None,  #component
                    self._va_config["streamar"]["repetition"]
                )

                ar_stream.repetition.subscribe(self.on_ar_rep)

            else:
                logging.warning("AR camera available, but no AR stream provided")

        else:
            parent_frame.fp_settings_sparc_angular.Hide()

    def on_spec_rep(self, rep):
        self._on_rep(rep, self.spectro_rep_ent.va, self.spectro_rep_ent.value_ctrl)

    def on_ar_rep(self, rep):
        self._on_rep(rep, self.angular_rep_ent.va, self.angular_rep_ent.value_ctrl)

    @staticmethod
    def _on_rep(rep, rep_va, rep_ctrl):
        """ Recalculate the repetition presets according to the ROI ratio """
        ratio = rep[1] / rep[0]

        # Create the entries:
        choices = [(1, 1)] # 1 x 1 should always be there

        # Add a couple values below/above the current repetition
        for m in [1/4, 1/2, 1, 2, 4, 10]:
            x = int(round(rep[0] * m))
            y = int(round(x * ratio))
            choices.append((x, y))

        # remove non-possible ones
        def is_compatible(c):
            # TODO: it's actually further restricted by the current size of
            # the ROI (and the minimum size of the pixelSize), so some of the
            # big repetitions might actually not be valid. It's not a big
            # problem as the VA setter will silently limit the repetition
            return (rep_va.range[0][0] <= c[0] <= rep_va.range[1][0] and
                    rep_va.range[0][1] <= c[1] <= rep_va.range[1][1])
        choices = [c for c in choices if is_compatible(c)]

        # remove duplicates and sort
        choices = sorted(set(choices))

        # replace the old list with this new version
        rep_ctrl.Clear()
        for c in choices:
            rep_ctrl.Append(u"%s x %s px" % c, c)


class AnalysisSettingsController(SettingsBarController):
    """ Control the widgets/settings in the right column of the analysis tab """

    def __init__(self, parent, tab_data):
        super(AnalysisSettingsController, self).__init__(tab_data)

        self.parent = parent
        # Gui data model
        self.tab_data = tab_data

        # We add 3 different panels so, they can each be hidden/shown
        # individually
        self._pnl_acqfile = None
        self._pnl_arfile = None
        self._specfile_controller = None

        self._arfile_ctrl = None
        self._spec_bckfile_ctrl = None
        self._specfile_ctrl = None

        self._create_controls()

        # Subscribe to the VAs that influence how the settings look.
        # All these VAs contain FileInfo object
        tab_data.acq_fileinfo.subscribe(self.on_acqfile_change, init=True)

        # The following three can be replaced by callables taking a unicode and
        # returning a unicode (or raising a ValueError exception). They are
        # "filters" on what value can be accepted when changing the calibration
        # files. (Typically, the tab controller will put some of its functions)
        self.setter_ar_file = None
        self.setter_spec_bck_file = None
        self.setter_spec_file = None

    def _create_controls(self):
        """ Create the default controls

        We create a Panel for each group of controls that we need to be able
        to show and hide separately.

        ** AR background and Spectrum efficiency compensation **

        These two controls are linked using VAs in the tab_data model.

        The controls are also linked to the VAs using event handlers, so that
        they can pass on their changing data.
        """

        ### Panel containing information about the acquisition file
        self._pnl_acqfile = FileInfoSettingsController(self.parent.fp_fileinfo, "No file loaded")

        ### Panel with AR background file information
        # It's displayed only if there are AR streams (handled by the tab cont)
        self._pnl_arfile = FileInfoSettingsController(self.parent.fp_fileinfo, "")
        self._arfile_ctrl = self._pnl_arfile.add_browse_button(
            "AR background",
            "Angle-resolved background acquisition file",
            "None").value_ctrl
        wildcards, _ = odemis.gui.util.formats_to_wildcards(odemis.dataio.get_available_formats(),
                                                            include_all=True)
        self._arfile_ctrl.SetWildcard(wildcards)
        self._pnl_arfile.hide_panel()
        self._arfile_ctrl.Bind(EVT_FILE_SELECT, self._on_ar_file_select)
        self.tab_data.ar_cal.subscribe(self._on_ar_cal, init=True)

        # Panel with spectrum background + efficiency compensation file information
        # They are displayed only if there are Spectrum streams
        self._specfile_controller = FileInfoSettingsController(self.parent.fp_fileinfo, "")
        self._spec_bckfile_ctrl = self._specfile_controller.add_browse_button(
            "Spec. background",
            "Spectrum background correction file",
            "None").value_ctrl
        self._spec_bckfile_ctrl.SetWildcard(wildcards)
        self._spec_bckfile_ctrl.Bind(EVT_FILE_SELECT, self._on_spec_bck_file_select)
        self.tab_data.spec_bck_cal.subscribe(self._on_spec_bck_cal, init=True)

        self._specfile_ctrl = self._specfile_controller.add_browse_button(
            "Spec. correction",
            "Spectrum efficiency correction file",
            "None").value_ctrl
        self._specfile_ctrl.SetWildcard(wildcards)
        self._specfile_controller.hide_panel()
        self._specfile_ctrl.Bind(EVT_FILE_SELECT, self._on_spec_file_select)
        self.tab_data.spec_cal.subscribe(self._on_spec_cal, init=True)

        self.parent.fp_fileinfo.expand()

    def on_acqfile_change(self, file_info):
        """ Display the name and location of the file described by file_info

        The controls in the acquisition file panel can be destroyed and
        re-created each time, because it's one-way traffic between the VA and
        the controls.

        """

        # Remove the old controls
        self._pnl_acqfile.panel.clear_all()

        if file_info:
            lc, vc = self._pnl_acqfile.panel.add_readonly_field("File", file_info.file_basename)
            # Make sure the end is visible
            vc.SetInsertionPointEnd()

            lc, vc = self._pnl_acqfile.panel.add_readonly_field("Path", file_info.file_path)
            vc.SetInsertionPointEnd()

            # Add any meta data as labels
            for key, value in file_info.metadata.items():
                self._pnl_acqfile.add_metadata(key, value)

        self._pnl_acqfile.Refresh()

    # TODO: refactor into widgets.FileConnector
    def _on_ar_file_select(self, evt):
        """ Pass the selected AR background file on to the VA """
        logging.debug("AR background selected by user")
        fn = evt.selected_file or u"" # selected_file is None if no file
        if self.setter_ar_file:
            try:
                fn = self.setter_ar_file(fn)
            except ValueError:
                logging.debug(u"Setter refused the file '%s'", fn)
                # Put back old file name
                self._arfile_ctrl.SetValue(self.tab_data.ar_cal.value)
                return
            except Exception:
                self._arfile_ctrl.SetValue(self.tab_data.ar_cal.value)
                raise

        self.tab_data.ar_cal.value = fn

    def _on_spec_bck_file_select(self, evt):
        """ Pass the selected spec background file on to the VA """
        logging.debug("Spectrum background file selected by user")
        fn = evt.selected_file or u""
        if self.setter_spec_bck_file:
            try:
                fn = self.setter_spec_bck_file(fn)
            except ValueError:
                logging.debug(u"Setter refused the file '%s'", fn)
                # Put back old file name
                self._spec_bckfile_ctrl.SetValue(self.tab_data.spec_bck_cal.value)
                return
            except Exception:
                self._spec_bckfile_ctrl.SetValue(self.tab_data.spec_bck_cal.value)
                raise

        self.tab_data.spec_bck_cal.value = fn

    def _on_spec_file_select(self, evt):
        """ Pass the selected efficiency compensation file on to the VA """
        logging.debug("Efficiency compensation file selected by user")
        fn = evt.selected_file or u""
        if self.setter_spec_file:
            try:
                fn = self.setter_spec_file(fn)
            except ValueError:
                logging.debug(u"Setter refused the file '%s'", fn)
                # Put back old file name
                self._specfile_ctrl.SetValue(self.tab_data.spec_cal.value)
                return
            except Exception:
                self._specfile_ctrl.SetValue(self.tab_data.spec_cal.value)
                raise

        self.tab_data.spec_cal.value = fn

    def _on_ar_cal(self, val):
        self._arfile_ctrl.SetValue(val)

    def _on_spec_bck_cal(self, val):
        self._spec_bckfile_ctrl.SetValue(val)

    def _on_spec_cal(self, val):
        self._specfile_ctrl.SetValue(val)

    def show_calibration_panel(self, ar=None, spec=None):
        """ Show/hide the the ar/spec panels

        ar (boolean or None): show, hide or don't change AR calib panel
        spec (boolean or None): show, hide or don't change spec calib panel

        """

        if ar is not None:
            self._pnl_arfile.show_panel(ar)
        if spec is not None:
            self._specfile_controller.show_panel(spec)

        self.parent.Layout()


class SparcAlignSettingsController(SettingsBarController):

    def __init__(self, parent_frame, tab_data):
        super(SparcAlignSettingsController, self).__init__(tab_data)
        main_data = tab_data.main

        self._ar_panel = AngularSettingsController(
                                parent_frame.fp_ma_settings_ar,
                                "No angle-resolved camera found")
        self._spectrum_panel = SpectrumSettingsController(
                                    parent_frame.fp_ma_settings_spectrum,
                                    "No spectrometer found")

        if main_data.ccd:
            self.add_component("Camera", main_data.ccd, self._ar_panel)

        if main_data.spectrometer:
            self.add_component(
                    "Spectrometer",
                    main_data.spectrometer,
                    self._spectrum_panel
            )
            # Add a intensity/time graph
            self.spec_graph = hist.Histogram(self._spectrum_panel.panel,
                                        size=(-1, 40))
            self.spec_graph.SetBackgroundColour("#000000")
            self._spectrum_panel.add_widgets(self.spec_graph)
            # the "Mean" value bellow the graph
            lbl_mean = wx.StaticText(self._spectrum_panel.panel, label="Mean")
            tooltip_txt = "Average intensity value of the last image"
            lbl_mean.SetToolTipString(tooltip_txt)
            self.txt_mean = wx.TextCtrl(self._spectrum_panel.panel, style=wx.BORDER_NONE | wx.TE_READONLY)
            self.txt_mean.SetForegroundColour(odemis.gui.FG_COLOUR_DIS)
            self.txt_mean.SetBackgroundColour(odemis.gui.BG_COLOUR_MAIN)
            self.txt_mean.SetToolTipString(tooltip_txt)
            self._spectrum_panel.add_widgets(lbl_mean, self.txt_mean)

