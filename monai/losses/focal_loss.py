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

import warnings
from typing import Optional, Sequence, Union

import torch
import torch.nn.functional as F
from torch.nn.modules.loss import _Loss

from monai.networks import one_hot
from monai.utils import LossReduction


class FocalLoss(_Loss):
    """
    Reimplementation of the Focal Loss (with a build-in sigmoid activation) described in:

        - "Focal Loss for Dense Object Detection", T. Lin et al., ICCV 2017
        - "AnatomyNet: Deep learning for fast and fully automated whole‐volume segmentation of head and neck anatomy",
          Zhu et al., Medical Physics 2018
    """

    def __init__(
        self,
        include_background: bool = True,
        to_onehot_y: bool = False,
        gamma: float = 2.0,
        weight: Optional[Union[Sequence[float], float, int, torch.Tensor]] = None,
        reduction: Union[LossReduction, str] = LossReduction.MEAN,
    ) -> None:
        """
        Args:
            include_background: if False, channel index 0 (background category) is excluded from the calculation.
            to_onehot_y: whether to convert `y` into the one-hot format. Defaults to False.
            gamma: value of the exponent gamma in the definition of the Focal loss.
            weight: weights to apply to the voxels of each class. If None no weights are applied.
                This corresponds to the weights `\alpha` in [1].
                The input can be a single value (same weight for all classes), a sequence of values (the length
                of the sequence should be the same as the number of classes, if not ``include_background``, the
                number should not include class 0).
                The value/values should be no less than 0. Defaults to None.
            reduction: {``"none"``, ``"mean"``, ``"sum"``}
                Specifies the reduction to apply to the output. Defaults to ``"mean"``.

                - ``"none"``: no reduction will be applied.
                - ``"mean"``: the sum of the output will be divided by the number of elements in the output.
                - ``"sum"``: the output will be summed.

        Example:
            .. code-block:: python

                import torch
                from monai.losses import FocalLoss

                pred = torch.tensor([[1, 0], [0, 1], [1, 0]], dtype=torch.float32)
                grnd = torch.tensor([[0], [1], [0]], dtype=torch.int64)
                fl = FocalLoss(to_onehot_y=True)
                fl(pred, grnd)

        """
        super().__init__(reduction=LossReduction(reduction).value)
        self.include_background = include_background
        self.to_onehot_y = to_onehot_y
        self.gamma = gamma
        self.weight: Optional[Union[Sequence[float], float, int, torch.Tensor]] = weight

    def forward(self, input: torch.Tensor, target: torch.Tensor) -> torch.Tensor:
        """
        Args:
            input: the shape should be BNH[WD], where N is the number of classes.
                The input should be the original logits since it will be transformed by
                a sigmoid in the forward function.
            target: the shape should be BNH[WD] or B1H[WD], where N is the number of classes.

        Raises:
            ValueError: When input and target (after one hot transform if set)
                have different shapes.
            ValueError: When ``self.reduction`` is not one of ["mean", "sum", "none"].
            ValueError: When ``self.weight`` is a sequence and the length is not equal to the
                number of classes.
            ValueError: When ``self.weight`` is/contains a value that is less than 0.

        """
        n_pred_ch = input.shape[1]

        if self.to_onehot_y:
            if n_pred_ch == 1:
                warnings.warn("single channel prediction, `to_onehot_y=True` ignored.")
            else:
                target = one_hot(target, num_classes=n_pred_ch)

        if not self.include_background:
            if n_pred_ch == 1:
                warnings.warn("single channel prediction, `include_background=False` ignored.")
            else:
                # if skipping background, removing first channel
                target = target[:, 1:]
                input = input[:, 1:]

        if target.shape != input.shape:
            raise ValueError(f"ground truth has different shape ({target.shape}) from input ({input.shape})")

        i = input
        t = target

        # Change the shape of input and target to B x N x num_voxels.
        b, n = t.shape[:2]
        i = i.reshape(b, n, -1)
        t = t.reshape(b, n, -1)

        # computing binary cross entropy with logits
        # see also https://github.com/pytorch/pytorch/blob/v1.9.0/aten/src/ATen/native/Loss.cpp#L231
        max_val = (-i).clamp(min=0)
        ce = i - i * t + max_val + ((-max_val).exp() + (-i - max_val).exp()).log()

        if self.weight is not None:
            class_weight: Optional[torch.Tensor] = None
            if isinstance(self.weight, (float, int)):
                class_weight = torch.as_tensor([self.weight] * i.size(1))
            else:
                class_weight = torch.as_tensor(self.weight)
                if class_weight.size(0) != i.size(1):
                    raise ValueError(
                        "the length of the weight sequence should be the same as the number of classes. "
                        + "If `include_background=False`, the number should not include class 0."
                    )
            if class_weight.min() < 0:
                raise ValueError("the value/values of weights should be no less than 0.")
            class_weight = class_weight.to(i)
            # Convert the weight to a map in which each voxel
            # has the weight associated with the ground-truth label
            # associated with this voxel in target.
            at = class_weight[None, :, None]  # N => 1,N,1
            at = at.expand((t.size(0), -1, t.size(2)))  # 1,N,1 => B,N,H*W
            # Multiply the log proba by their weights.
            ce = ce * at

        # Compute the loss mini-batch.
        # (1-p_t)^gamma * log(p_t) with reduced chance of overflow
        p = F.logsigmoid(-i * (t * 2.0 - 1.0))
        loss = torch.mean((p * self.gamma).exp() * ce, dim=-1)

        if self.reduction == LossReduction.SUM.value:
            return loss.sum()
        if self.reduction == LossReduction.NONE.value:
            return loss
        if self.reduction == LossReduction.MEAN.value:
            return loss.mean()
        raise ValueError(f'Unsupported reduction: {self.reduction}, available options are ["mean", "sum", "none"].')
