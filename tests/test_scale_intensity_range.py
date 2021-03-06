# Copyright 2020 - 2021 MONAI Consortium
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#     http://www.apache.org/licenses/LICENSE-2.0
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import unittest

from monai.transforms import ScaleIntensityRange
from tests.utils import TEST_NDARRAYS, NumpyImageTestCase2D, assert_allclose


class IntensityScaleIntensityRange(NumpyImageTestCase2D):
    def test_image_scale_intensity_range(self):
        scaler = ScaleIntensityRange(a_min=20, a_max=108, b_min=50, b_max=80)
        for p in TEST_NDARRAYS:
            scaled = scaler(p(self.imt))
            expected = (self.imt - 20) / 88
            expected = expected * 30 + 50
            assert_allclose(scaled, p(expected))


if __name__ == "__main__":
    unittest.main()
