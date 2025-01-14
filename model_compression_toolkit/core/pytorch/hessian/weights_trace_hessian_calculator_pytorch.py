# Copyright 2023 Sony Semiconductor Israel, Inc. All rights reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
# ==============================================================================

from typing import List
import torch
from torch import autograd
import numpy as np
from model_compression_toolkit.core.common import Graph
from model_compression_toolkit.core.common.hessian import TraceHessianRequest, HessianInfoGranularity
from model_compression_toolkit.core.pytorch.hessian.trace_hessian_calculator_pytorch import \
    TraceHessianCalculatorPytorch
from model_compression_toolkit.logger import Logger
from model_compression_toolkit.core.pytorch.back2framework.float_model_builder import FloatPyTorchModelBuilder
from model_compression_toolkit.core.pytorch.default_framework_info import DEFAULT_PYTORCH_INFO
from model_compression_toolkit.constants import HESSIAN_NUM_ITERATIONS, MIN_HESSIAN_ITER, HESSIAN_COMP_TOLERANCE, HESSIAN_EPS


class WeightsTraceHessianCalculatorPytorch(TraceHessianCalculatorPytorch):
    """
    Pytorch-specific implementation of the Trace Hessian approximation computation w.r.t node's weights.
    """

    def __init__(self,
                 graph: Graph,
                 input_images: List[torch.Tensor],
                 fw_impl,
                 trace_hessian_request: TraceHessianRequest,
                 num_iterations_for_approximation: int = HESSIAN_NUM_ITERATIONS):
        """

        Args:
            graph: Computational graph for the float model.
            input_images: List of input images for the computation.
            fw_impl: Framework-specific implementation for trace Hessian computation.
            trace_hessian_request: Configuration request for which to compute the trace Hessian approximation.
            num_iterations_for_approximation: Number of iterations to use when approximating the Hessian trace.
        """
        super(WeightsTraceHessianCalculatorPytorch, self).__init__(graph=graph,
                                                                   input_images=input_images,
                                                                   fw_impl=fw_impl,
                                                                   trace_hessian_request=trace_hessian_request,
                                                                   num_iterations_for_approximation=num_iterations_for_approximation)


    def compute(self) -> np.ndarray:
        """
        Compute the Hessian-based scores w.r.t target node's weights.
        The computed scores are returned in a numpy array. The shape of the result differs
        according to the requested granularity. If for example the node is Conv2D with a kernel
        shape of (2, 3, 3, 3) (namely, 3 input channels, 2 output channels and kernel size of 3x3)
        and the required granularity is HessianInfoGranularity.PER_TENSOR the result shape will be (1,),
        for HessianInfoGranularity.PER_OUTPUT_CHANNEL the shape will be (2,) and for
        HessianInfoGranularity.PER_ELEMENT a shape of (2, 3, 3, 3).

        Returns:
            The computed scores as numpy ndarray for target node's weights.
        """

        # Check if the target node's layer type is supported
        if not DEFAULT_PYTORCH_INFO.is_kernel_op(self.hessian_request.target_node.type):
            Logger.error(f"{self.hessian_request.target_node.type} is not supported for Hessian info w.r.t weights.")  # pragma: no cover

        # Float model
        model, _ = FloatPyTorchModelBuilder(graph=self.graph).build_model()

        # Get the weight attributes for the target node type
        weights_attributes = DEFAULT_PYTORCH_INFO.get_kernel_op_attributes(self.hessian_request.target_node.type)

        # Get the weight tensor for the target node
        if len(weights_attributes) != 1:
            Logger.error(f"Hessian scores w.r.t weights is supported, for now, for a single-weight node. Found {len(weights_attributes)}")

        weights_tensor = getattr(getattr(model,self.hessian_request.target_node.name),weights_attributes[0])

        # Get the output channel index
        output_channel_axis, _ = DEFAULT_PYTORCH_INFO.kernel_channels_mapping.get(self.hessian_request.target_node.type)
        shape_channel_axis = [i for i in range(len(weights_tensor.shape))]
        if self.hessian_request.granularity == HessianInfoGranularity.PER_OUTPUT_CHANNEL:
            shape_channel_axis.remove(output_channel_axis)
        elif self.hessian_request.granularity == HessianInfoGranularity.PER_ELEMENT:
            shape_channel_axis = ()

        # Run model inference
        outputs = model(self.input_images)
        output_tensor = self.concat_tensors(outputs)
        device = output_tensor.device

        approximation_per_iteration = []
        for j in range(self.num_iterations_for_approximation):
            # Getting a random vector with normal distribution and the same shape as the model output
            v = torch.randn_like(output_tensor, device=device)
            f_v = torch.mean(torch.sum(v * output_tensor, dim=-1))
            # Compute gradients of f_v with respect to the weights
            f_v_grad = autograd.grad(outputs=f_v,
                                     inputs=weights_tensor,
                                     retain_graph=True)[0]

            # Trace{A^T * A} = sum of all squares values of A
            approx = f_v_grad ** 2
            if len(shape_channel_axis) > 0:
                approx = torch.sum(approx, dim=shape_channel_axis)

            if j > MIN_HESSIAN_ITER:
                new_mean = (torch.sum(torch.stack(approximation_per_iteration), dim=0) + approx)/(j+1)
                delta = new_mean - torch.mean(torch.stack(approximation_per_iteration), dim=0)
                converged_tensor = torch.abs(delta) / (torch.abs(new_mean) + HESSIAN_EPS) < HESSIAN_COMP_TOLERANCE
                if torch.all(converged_tensor):
                    break

            approximation_per_iteration.append(approx)

        # Compute the mean of the approximations
        final_approx = torch.mean(torch.stack(approximation_per_iteration), dim=0)

        # Make sure all final shape are tensors and not scalar
        if self.hessian_request.granularity == HessianInfoGranularity.PER_TENSOR:
            final_approx = final_approx.reshape(1)

        return final_approx.detach().cpu().numpy()

