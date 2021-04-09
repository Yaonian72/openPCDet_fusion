import copy
import pickle

import numpy as np
from skimage import io

from pathlib import Path
from ...ops.roiaware_pool3d import roiaware_pool3d_utils
from ...utils import box_utils, calibration_kitti, common_utils, object3d_kitti
from .kitti_dataset import KittiDataset


class KittiDatasetPainted(KittiDataset):


