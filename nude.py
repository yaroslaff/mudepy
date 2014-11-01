#!/usr/bin/env python
# encoding: utf-8

from __future__ import (absolute_import, division,
                        print_function, unicode_literals)

import copy
import sys
from collections import namedtuple

try:
    import Image
except ImportError:
    try:
        from PIL import Image
    except ImportError:
        sys.stderr.write("Please install PIL or Pillow\n")
        sys.exit(1)


def is_nude(path_or_io):
    nude = Nude(path_or_io)
    return nude.parse().result


class Nude(object):

    Skin = namedtuple("Skin", "id skin region x y checked")

    def __init__(self, path_or_io):
        if isinstance(Image, type(path_or_io)):
            self.image = path_or_io
        else:
            self.image = Image.open(path_or_io)
        bands = self.image.getbands()
        # convert greyscale to rgb
        if len(bands) == 1:
            new_img = Image.new("RGB", self.image.size)
            new_img.paste(self.image)
            f = self.image.filename
            self.image = new_img
            self.image.filename = f
        self.skin_map = []
        self.skin_regions = []
        self.detected_regions = []
        self.merge_regions = []
        self.last_from, self.last_to = -1, -1
        self.result = None
        self.message = None
        self.width, self.height = self.image.size
        self.total_pixels = self.width * self.height

    def parse(self):
        if self.result:
            return self

        pixels = self.image.load()
        for y in range(self.height):
            for x in range(self.width):
                r = pixels[x, y][0]   # red
                g = pixels[x, y][1]   # green
                b = pixels[x, y][2]   # blue
                _id = x + y * self.width + 1

                if not self._classify_skin(r, g, b):
                    self.skin_map.append(self.Skin(_id, False, 0, x, y, False))
                else:
                    self.skin_map.append(self.Skin(_id, True, 0, x, y, False))

                    region = -1
                    check_indexes = [_id - 2,
                                     _id - self.width - 2,
                                     _id - self.width - 1,
                                     _id - self.width]
                    checker = False

                    for index in check_indexes:
                        try:
                            self.skin_map[index]
                        except IndexError:
                            break
                        if self.skin_map[index].skin:
                            if (self.skin_map[index].region != region and
                                    region != -1 and
                                    self.last_from != region and
                                    self.last_to != self.skin_map[index].region):
                                self._add_merge(region, self.skin_map[index].region)
                            region = self.skin_map[index].region
                            checker = True

                    if not checker:
                        _skin = self.skin_map[_id - 1]._replace(region=len(self.detected_regions))
                        self.skin_map[_id - 1] = _skin
                        self.detected_regions.append([self.skin_map[_id - 1]])
                        continue
                    else:
                        if region > -1:
                            try:
                                self.detected_regions[region]
                            except IndexError:
                                self.detected_regions.append([])
                            _skin = self.skin_map[_id - 1]._replace(region=region)
                            self.skin_map[_id - 1] = _skin
                            self.detected_regions[region].append(self.skin_map[_id - 1])

        self._merge(self.detected_regions, self.merge_regions)
        self._analyse_regions()
        return self

    def inspect(self):
        _nude_class = "{_module}.{_class}:{_addr}".format(_module=self.__class__.__module__,
                                                          _class=self.__class__.__name__,
                                                          _addr=hex(id(self)))
        _image = "'%s' '%s' '%dx%d'" % (self.image.filename, self.image.format, self.width, self.height)
        return "#<{_nude_class}({_image}): result={_result} message='{_message}'>".format(
            _nude_class=_nude_class, _image=_image, _result=self.result, _message=self.message)

    def _add_merge(self, _from, _to):
        self.last_from = _from
        self.last_to = _to
        from_index = -1
        to_index = -1

        for index, region in enumerate(self.merge_regions):
            for r_index in region:
                if r_index == _from:
                    from_index = index
                if r_index == _to:
                    to_index = index

        if from_index != -1 and to_index != -1:
            if from_index != to_index:
                _tmp = copy.copy(self.merge_regions[from_index])
                _tmp.extend(self.merge_regions[to_index])
                self.merge_regions[from_index] = _tmp
                del(self.merge_regions[to_index])
            return

        if from_index == -1 and to_index == -1:
            self.merge_regions.append([_from, _to])
            return

        if from_index != -1 and to_index == -1:
            self.merge_regions[from_index].append(_to)
            return

        if from_index == -1 and to_index != -1:
            self.merge_regions[to_index].append(_from)
            return

    # function for merging detected regions
    def _merge(self, detected_regions, merge_regions):
        new_detected_regions = []

        # merging detected regions
        for index, region in enumerate(merge_regions):
            try:
                new_detected_regions[index]
            except IndexError:
                new_detected_regions.append([])
            for r_index in region:
                _tmp = copy.copy(new_detected_regions[index])
                _tmp.extend(detected_regions[r_index])
                new_detected_regions[index] = _tmp
                detected_regions[r_index] = []

        # push the rest of the regions to the detRegions array
        # (regions without merging)
        for region in detected_regions:
            if len(region) > 0:
                new_detected_regions.append(region)

        # clean up
        self._clear_regions(new_detected_regions)

    # clean up function
    # only pushes regions which are bigger than a specific amount to the final result
    def _clear_regions(self, detected_regions):
        for region in detected_regions:
            if len(region) > 30:
                self.skin_regions.append(region)

    def _analyse_regions(self):
        # if there are less than 3 regions
        if len(self.skin_regions) < 3:
            self.message = "Less than 3 skin regions ({_skin_regions_size})".format(
                _skin_regions_size=len(self.skin_regions))
            self.result = False
            return self.result

        # sort the skin regions
        self.skin_regions = sorted(self.skin_regions, key=lambda s: len(s))
        self.skin_regions.reverse()

        # count total skin pixels
        total_skin = float(sum([len(skin_region) for skin_region in self.skin_regions]))

        # check if there are more than 15% skin pixel in the image
        if total_skin / self.total_pixels * 100 < 15:
            # if the percentage lower than 15, it's not nude!
            self.message = "Total skin parcentage lower than 15 (%.3f%%)" % (total_skin / self.total_pixels * 100)
            self.result = False
            return self.result

        # check if the largest skin region is less than 35% of the total skin count
        # AND if the second largest region is less than 30% of the total skin count
        # AND if the third largest region is less than 30% of the total skin count
        if len(self.skin_regions[0]) / total_skin * 100 < 35 and \
           len(self.skin_regions[1]) / total_skin * 100 < 30 and \
           len(self.skin_regions[2]) / total_skin * 100 < 30:
            self.message = 'Less than 35%, 30%, 30% skin in the biggest regions'
            self.result = False
            return self.result

        # check if the number of skin pixels in the largest region is less than 45% of the total skin count
        if len(self.skin_regions[0]) / total_skin * 100 < 45:
            self.message = "The biggest region contains less than 45 (%.3f%%)" % (len(self.skin_regions[0]) / total_skin * 100)
            self.result = False
            return self.result

        # TODO:
        # build the bounding polygon by the regions edge values:
        # Identify the leftmost, the uppermost, the rightmost, and the lowermost skin pixels of the three largest skin regions.
        # Use these points as the corner points of a bounding polygon.

        # TODO:
        # check if the total skin count is less than 30% of the total number of pixels
        # AND the number of skin pixels within the bounding polygon is less than 55% of the size of the polygon
        # if this condition is True, it's not nude.

        # TODO: include bounding polygon functionality
        # if there are more than 60 skin regions and the average intensity within the polygon is less than 0.25
        # the image is not nude
        if len(self.skin_regions) > 60:
            self.message = "More than 60 skin regions ({_skin_regions_size})".format(
                _skin_regions_size=len(self.skin_regions))
            self.result = False
            return self.result

        # otherwise it is nude
        self.message = "Nude!!"
        self.result = True
        return self.result

    # A Survey on Pixel-Based Skin Color Detection Techniques
    def _classify_skin(self, r, g, b):
        rgb_classifier = r > 95 and \
            g > 40 and g < 100 and \
            b > 20 and \
            max([r, g, b]) - min([r, g, b]) > 15 and \
            abs(r - g) > 15 and \
            r > g and \
            r > b

        nr, ng, nb = self._to_normalized_rgb(r, g, b)
        norm_rgb_classifier = nr / ng > 1.185 and \
            float(r * b) / ((r + g + b) ** 2) > 0.107 and \
            float(r * g) / ((r + g + b) ** 2) > 0.112

        h, s, v = self._to_hsv(r, g, b)
        hsv_classifier = h > 0 and \
            h < 35 and \
            s > 0.23 and \
            s < 0.68

        # ycc doesnt work
        return rgb_classifier or norm_rgb_classifier or hsv_classifier

    def _to_normalized_rgb(self, r, g, b):
        if r == 0:
            r = 0.0001
        if g == 0:
            g = 0.0001
        if b == 0:
            b = 0.0001
        _sum = float(r + g + b)
        return [r / _sum, g / _sum, b / _sum]

    def _to_hsv(self, r, g, b):
        h = 0
        _sum = float(r + g + b)
        _max = float(max([r, g, b]))
        _min = float(min([r, g, b]))
        diff = float(_max - _min)
        if _sum == 0:
            _sum = 0.0001

        if _max == r:
            if diff == 0:
                h = sys.maxsize
            else:
                h = (g - b) / diff
        elif _max == g:
            h = 2 + ((g - r) / diff)
        else:
            h = 4 + ((r - g) / diff)

        h *= 60
        if h < 0:
            h += 360

        return [h, 1.0 - (3.0 * (_min / _sum)), (1.0 / 3.0) * _max]

##############################################################################


def main():
    if len(sys.argv) < 2:
        print("Usage: {0} <image>".format(sys.argv[0]))
        return 1
    # else
    fname = sys.argv[1]
    print(is_nude(fname))

    n = Nude(fname)
    n.parse()
    print("{0}: {1} {2}".format(fname, n.result, n.inspect()))
    return 0

if __name__ == "__main__":
    sys.exit(main())