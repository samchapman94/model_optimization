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

from model_compression_toolkit.core.common.hessian.trace_hessian_calculator import TraceHessianCalculator

from typing import List, Tuple, Dict, Any, Union

import tensorflow as tf
from tensorflow.python.keras.engine.base_layer import Layer
from model_compression_toolkit.constants import HESSIAN_NUM_ITERATIONS
from model_compression_toolkit.core.common.graph.edge import EDGE_SINK_INDEX
from model_compression_toolkit.core.common import Graph, BaseNode
from model_compression_toolkit.core.common.graph.functional_node import FunctionalNode
from model_compression_toolkit.core.common.hessian import TraceHessianRequest
from model_compression_toolkit.core.keras.back2framework.instance_builder import OperationHandler
from tensorflow.python.util.object_identity import Reference as TFReference

from model_compression_toolkit.logger import Logger


class TraceHessianCalculatorKeras(TraceHessianCalculator):
    """
    Keras-specific implementation of the Trace Hessian approximation Calculator.
    This class serves as a base for other Keras-specific trace Hessian approximation calculators.
    """
    def __init__(self,
                 graph: Graph,
                 input_images: List[tf.Tensor],
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
        super(TraceHessianCalculatorKeras, self).__init__(graph=graph,
                                                          input_images=input_images,
                                                          fw_impl=fw_impl,
                                                          trace_hessian_request=trace_hessian_request,
                                                          num_iterations_for_approximation=num_iterations_for_approximation)

    def _concat_tensors(self, tensors_to_concate: Union[tf.Tensor, List[tf.Tensor]]) -> tf.Tensor:
        """
        Concatenate tensors into a single tensor.

        Args:
            tensors_to_concate: Tensors to concatenate.

        Returns:
            tf.Tensor of the concatenation of the tensors.

        """
        _unfold_tensors = self.unfold_tensors_list(tensors_to_concate)
        _r_tensors = [tf.reshape(tensor, shape=[tensor.shape[0], -1]) for tensor in _unfold_tensors]

        # Ensure all tensors have the same shape for concatenation
        concat_axis_dim = [o.shape[0] for o in _r_tensors]
        if not all(d == concat_axis_dim[0] for d in concat_axis_dim):
            Logger.critical(
                "Can't concat model's outputs for gradients calculation since the shape of the first axis "  # pragma: no cover  
                "is not equal in all outputs.")

        return tf.concat(_r_tensors, axis=1)
