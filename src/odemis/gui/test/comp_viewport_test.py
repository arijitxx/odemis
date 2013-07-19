#-*- coding: utf-8 -*-

"""
@author: Rinze de Laat

Copyright © 2013 Rinze de Laat, Delmic

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

#===============================================================================
# Test module for Odemis' gui.comp.buttons module
#===============================================================================

import unittest

import wx

import odemis.gui.comp.canvas as canvas
import odemis.gui.comp.viewport as viewport
import odemis.gui.test.test_gui


from odemis.gui.xmlh import odemis_get_test_resources
from odemis.gui.test import MANUAL, SLEEP_TIME, gui_loop
from odemis.gui.canvas import ZeroDimensionalPlotCanvas

INSPECT = False
MANUAL = True

PLOTS = [
    ([0, 1, 2, 3, 4, 5], [1, 3, 5, 2, 4, 0]),
    ([0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24, 25, 26, 27, 28, 29, 30, 31, 32, 33, 34, 35, 36, 37, 38, 39, 40, 41, 42, 43, 44, 45, 46, 47, 48, 49, 50, 51, 52, 53, 54, 55, 56, 57, 58, 59, 60, 61, 62, 63, 64, 65, 66, 67, 68, 69, 70, 71, 72, 73, 74, 75, 76, 77, 78, 79, 80, 81, 82, 83, 84, 85, 86, 87, 88, 89, 90, 91, 92, 93, 94, 95, 96, 97, 98, 99, 100, 101, 102, 103, 104, 105, 106, 107, 108, 109, 110, 111, 112, 113, 114, 115, 116, 117, 118, 119, 120, 121, 122, 123, 124, 125, 126, 127], [15, 29, 29, 34, 42, 48, 62, 64, 71, 88, 94, 95, 104, 117, 124, 126, 140, 144, 155, 158, 158, 172, 186, 205, 214, 226, 234, 244, 248, 265, 280, 299, 312, 314, 317, 321, 333, 335, 337, 343, 346, 346, 352, 370, 379, 384, 392, 411, 413, 431, 438, 453, 470, 477, 487, 495, 509, 512, 519, 527, 535, 544, 550, 555, 561, 574, 579, 582, 601, 605, 616, 619, 620, 633, 642, 658, 668, 687, 702, 716, 732, 745, 763, 779, 780, 780, 793, 803, 815, 815, 832, 851, 851, 866, 873, 890, 896, 906, 918, 919, 921, 922, 933, 934, 949, 949, 952, 963, 974, 974, 989, 989, 1002, 1012, 1031, 1046, 1053, 1062, 1066, 1074, 1085, 1092, 1097, 1097, 1098, 1103, 1105, 1116]),
    ([17, 36, 40, 43, 44, 62, 79, 83, 99, 104, 116, 133, 147, 152, 171, 185, 193, 195, 201, 210, 225, 225, 241, 246, 254, 254, 269, 270, 272, 280, 286, 304, 323, 336, 344, 345, 351, 355, 374, 381, 400, 408, 425, 444, 449, 456, 466, 482, 489, 506, 507, 516, 526, 542, 561, 576, 581, 593, 595, 602, 604, 618, 633, 639, 647, 656, 667, 670, 689, 691, 705, 721, 725, 738, 750, 767, 768, 776, 786, 797, 809, 809, 815, 832, 840, 857, 867, 869, 878, 889, 892, 905, 907, 915, 934, 952, 957, 971, 985, 1003, 1019, 1032, 1042, 1046, 1058, 1077, 1089, 1100, 1104, 1109, 1121, 1124, 1127, 1132, 1145, 1148, 1155, 1170, 1171, 1183, 1184, 1196, 1208, 1214, 1229, 1235, 1236, 1239], [0.0, 0.6365122726989454, 1.2723796780808552, 1.906958002160726, 2.53960433695571, 3.1696777318320972, 3.7965398428692474, 4.419555579582602, 5.0380937483505495, 5.651527691893277, 6.259235924155733, 6.860602759951489, 7.455018938729595, 8.041882241832447, 8.620598102619352, 9.19058020883762, 9.75125109663092, 10.30204273558309, 10.842397104204696, 11.371766755279262, 11.889615370496443, 12.395418303810198, 12.888663112971502, 13.368850078697054, 13.835492710948023, 14.28811824180589, 14.72626810444606, 15.149498397723974, 15.557380335903012, 15.949500683068614, 16.325462171788427, 16.68488390559441, 17.027401744879036, 17.352668675814723, 17.660355161922638, 17.9501494779348, 18.22175802561112, 18.474905631191508, 18.70933582418163, 18.924811097189927, 19.12111314655259, 19.29804309350273, 19.4554216856597, 19.593089478634386, 19.710906997566514, 19.8087548784303, 19.886533988965265, 19.94416552910976, 19.98159111083536, 19.998772817301322, 19.995693241269127, 19.972355502738214, 19.928783245785024, 19.86502061460857, 19.78113220880678, 19.677203017928953, 19.55333833537061, 19.40966365169799, 19.246324527510243, 19.063486445968188, 18.861334645138946, 18.640073930326405, 18.39992846657756, 18.141141551575032, 17.863975369145777, 17.568710723635768, 17.255646755419708, 16.925100637834095, 16.577407255840527, 16.212918866744978, 15.832004743316626, 15.435050799667964, 15.022459200275, 14.594647952533888, 14.152050483266645, 13.695115199605024, 13.2243050346975, 12.740096978699476, 12.242981595522055, 11.733462525828823, 11.212055976784281, 10.679290199070756, 10.135704951703774, 9.581850955187997, 9.018289333567836, 8.445591045937874, 7.86433630798924, 7.275114004177816, 6.678521091109944, 6.075161992749953, 5.465647988062376, 4.850596591709154, 4.230630928429297, 3.6063791017348503, 2.9784735575626757, 2.3475504435268717, 1.7142489644208867, 1.0792107346223752, 0.44307912805674976, 0.19350137362182113, 0.829885833971738, 1.4654295151659982, 2.0994885311930926, 2.731420500194814, 3.3605851952802257, 3.986345193156318, 4.608066519918359, 5.225119293345488, 5.836878361050961, 6.44272393384048, 7.042042213636877, 7.63422601533515, 8.218675381957603, 8.794798192486061, 9.3620107617552, 9.919738431799397, 10.467416154053764, 11.004489061819742, 11.530413032415103, 12.044655238438986, 12.546694687593318, 13.03602275051382, 13.512143676075766, 13.974575093652511, 14.422848501817834, 14.856509742997059, 15.275119463586035, 15.678253559071791]),
]

SCALES = [0.5, 1.0, 2.0, 4.0, 8.0, 16.0, 32.0, 64.0, 128.0, 256.0]

VIEW_SIZE = (400, 400)

# View coordinates, with a top-left 0,0 origin
VIEW_COORDS = [
                (0, 0),
                (0, 349),
                (123, 0),
                (321, 322),
              ]

# Margin around the view
MARGINS = [(0, 0), (512, 512)]

# Buffer coordinates, with a top-left 0,0 origin
BUFF_COORDS = [
                (0, 0),
                (0, 349),
                (512 + 200, 512 + 200),
                (133, 0),
                (399, 399),
              ]

# The center of the buffer, in world coordinates
BUFFER_CENTER = [(0.0, 0.0)]


class TestApp(wx.App):
    def __init__(self):
        odemis.gui.test.test_gui.get_resources = odemis_get_test_resources
        self.test_frame = None
        wx.App.__init__(self, redirect=False)

    def OnInit(self):
        self.test_frame = odemis.gui.test.test_gui.xrccanvas_frame(None)
        self.test_frame.SetSize((400, 400))
        self.test_frame.Center()
        self.test_frame.Layout()
        self.test_frame.Show()

        return True

class CanvasTestCase(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.app = TestApp()
        cls.panel = cls.app.test_frame.canvas_panel
        cls.sizer = cls.panel.GetSizer()

        # NOTE!: Call Layout on the panel here, because otherwise the
        # controls layed out using XRC will not have the right sizes!
        gui_loop()

    @classmethod
    def tearDownClass(cls):
        if not MANUAL:
            wx.CallAfter(cls.app.Exit)
        else:
            if INSPECT:
                from wx.lib import inspection
                inspection.InspectionTool().Show()
            cls.app.MainLoop()

    @classmethod
    def add_control(cls, ctrl, flags):
        cls.sizer.Add(ctrl, flag=flags|wx.ALL, border=0, proportion=1)
        cls.sizer.Layout()
        return ctrl

    def test_plot_viewport(self):
        vwp = viewport.PlotViewport(self.panel)

        vwp.SetBackgroundColour(wx.BLACK)
        vwp.SetForegroundColour("#DDDDDD")
        # vwp.set_closed(canvas.PLOT_CLOSE_STRAIGHT)
        self.add_control(vwp, wx.EXPAND)

        vwp.canvas.set_1d_data(PLOTS[-1][0], PLOTS[-1][1])


if __name__ == "__main__":
    unittest.main()