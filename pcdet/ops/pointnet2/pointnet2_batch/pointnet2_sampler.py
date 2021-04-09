import torch
from torch import nn as nn
from typing import List

from . import pointnet2_utils


def calc_square_dist(point_feat_a, point_feat_b, norm=True):
    """Calculating square distance between a and b.
    Args:
        point_feat_a (Tensor): (B, N, C) Feature vector of each point.
        point_feat_b (Tensor): (B, M, C) Feature vector of each point.
        norm (Bool): Whether to normalize the distance.
            Default: True.
    Returns:
        Tensor: (B, N, M) Distance between each pair points.
    """
    length_a = point_feat_a.shape[1]
    length_b = point_feat_b.shape[1]
    num_channel = point_feat_a.shape[-1]
    # [bs, n, 1]
    a_square = torch.sum(point_feat_a.unsqueeze(dim=2).pow(2), dim=-1)
    # [bs, 1, m]
    b_square = torch.sum(point_feat_b.unsqueeze(dim=1).pow(2), dim=-1)
    a_square = a_square.repeat((1, 1, length_b))  # [bs, n, m]
    b_square = b_square.repeat((1, length_a, 1))  # [bs, n, m]

    coor = torch.matmul(point_feat_a, point_feat_b.transpose(1, 2))

    dist = a_square + b_square - 2 * coor
    if norm:
        dist = torch.sqrt(dist) / num_channel
    return dist


def get_sampler_type(sampler_type):
    """Get the type and mode of points sampler.
    Args:
        sampler_type (str): The type of points sampler.
            The valid value are "D-FPS", "F-FPS", or "FS".
    Returns:
        class: Points sampler type.
    """
    if sampler_type == 'D-FPS':
        sampler = DFPS_Sampler
    elif sampler_type == 'F-FPS':
        sampler = FFPS_Sampler
    elif sampler_type == 'FS':
        sampler = FS_Sampler
    else:
        raise ValueError('Only "sampler_type" of "D-FPS", "F-FPS", or "FS"'
                         f' are supported, got {sampler_type}')

    return sampler


class Points_Sampler(nn.Module):
    """Points sampling.
    Args:
        num_point (list[int]): Number of sample points.
        fps_mod_list (list[str]: Type of FPS method, valid mod
            ['F-FPS', 'D-FPS', 'FS'], Default: ['D-FPS'].
            F-FPS: using feature distances for FPS.
            D-FPS: using Euclidean distances of points for FPS.
            FS: using F-FPS and D-FPS simultaneously.
        fps_sample_range_list (list[int]): Range of points to apply FPS.
            Default: [-1].
    """

    def __init__(self,
                 num_point: List[int],
                 fps_mod_list: List[str] = ['D-FPS'],
                 fps_sample_range_list: List[int] = [-1]):
        super(Points_Sampler, self).__init__()
        # FPS would be applied to different fps_mod in the list,
        # so the length of the num_point should be equal to
        # fps_mod_list and fps_sample_range_list.
        if isinstance(num_point, int):
            num_point = [num_point]
        assert len(num_point) == len(fps_mod_list) == len(
            fps_sample_range_list)
        self.num_point = num_point
        self.fps_sample_range_list = fps_sample_range_list
        self.samplers = nn.ModuleList()
        for fps_mod in fps_mod_list:
            self.samplers.append(get_sampler_type(fps_mod)())
        self.fp16_enabled = False

    def forward(self, points_xyz, features):
        """forward.
        Args:
            points_xyz (Tensor): (B, N, 3) xyz coordinates of the features.
            features (Tensor): (B, C, N) Descriptors of the features.
        Return：
            Tensor: (B, npoint, sample_num) Indices of sampled points.
        """
        indices = []
        last_fps_end_index = 0

        for fps_sample_range, sampler, npoint in zip(
                self.fps_sample_range_list, self.samplers, self.num_point):
            assert fps_sample_range < points_xyz.shape[1]

            if fps_sample_range == -1:
                sample_points_xyz = points_xyz[:, last_fps_end_index:]
                sample_features = features[:, :, last_fps_end_index:]
            else:
                sample_points_xyz = \
                    points_xyz[:, last_fps_end_index:fps_sample_range]
                sample_features = \
                    features[:, :, last_fps_end_index:fps_sample_range]

            fps_idx = sampler(sample_points_xyz.contiguous(), sample_features,
                              npoint)

            indices.append(fps_idx + last_fps_end_index)
            last_fps_end_index += fps_sample_range
        indices = torch.cat(indices, dim=1)

        return indices


class DFPS_Sampler(nn.Module):
    """DFPS_Sampling.
    Using Euclidean distances of points for FPS.
    """

    def __init__(self):
        super(DFPS_Sampler, self).__init__()

    def forward(self, points, features, npoint):
        """Sampling points with D-FPS."""
        fps_idx = pointnet2_utils.furthest_point_sample(points.contiguous(), npoint)
        return fps_idx


class FFPS_Sampler(nn.Module):
    """FFPS_Sampler.
    Using feature distances for FPS.
    """

    def __init__(self):
        super(FFPS_Sampler, self).__init__()

    def forward(self, points, features, npoint):
        """Sampling points with F-FPS."""
        features_for_fps = torch.cat([points, features.transpose(1, 2)], dim=2)
        features_dist = calc_square_dist(
            features_for_fps, features_for_fps, norm=False)
        fps_idx = pointnet2_utils.furthest_point_sample_with_dist(features_dist, npoint)
        return fps_idx


class FS_Sampler(nn.Module):
    """FS_Sampling.
    Using F-FPS and D-FPS simultaneously.
    """

    def __init__(self):
        super(FS_Sampler, self).__init__()

    def forward(self, points, features, npoint):
        """Sampling points with FS_Sampling."""
        features_for_fps = torch.cat([points, features.transpose(1, 2)], dim=2)
        features_dist = calc_square_dist(
            features_for_fps, features_for_fps, norm=False)
        fps_idx_ffps = pointnet2_utils.furthest_point_sample_with_dist(features_dist, npoint)
        fps_idx_dfps = pointnet2_utils.furthest_point_sample(points, npoint)
        fps_idx = torch.cat([fps_idx_ffps, fps_idx_dfps], dim=1)
        return fps_idx