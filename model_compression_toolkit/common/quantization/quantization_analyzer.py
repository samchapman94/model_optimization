# Copyright 2021 Sony Semiconductors Israel, Inc. All rights reserved.
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

from typing import Callable

from networkx.algorithms.dag import topological_sort

from model_compression_toolkit import common


def create_tensor2node(graph: common.Graph,
                       node: common.Node):
    """
    Force tensor creation and assignment for a node.
    Args:
        graph: Graph of the node (for retrieving the current tensor).
        node: Node to create a tensor for.

    """
    current_tensor = graph.get_out_stats_collector(node)
    if isinstance(current_tensor, common.NoStatsContainer) or current_tensor is None:
        graph.set_out_stats_collector_to_node(node, common.StatsContainer())


def analyzer_graph(node_analyze_func: Callable,
                   graph: common.Graph,
                   fw_info: common.FrameworkInfo,
                   qc: common.QuantizationConfig = common.DEFAULTCONFIG):
    """
    Go over all nodes in a graph, and create and set statistics collection tensors for each node's input and output.
    The tensors are stored in the graph.
    The kind of tensor that is created for each node is determined according to:
    node_analyze_func, groups mapping (operator to quantization treatment), and the overall quantization configuration.

    Args:
        fw_info: Information relevant to a specific framework about how layers should be quantized.
        node_analyze_func: Function which returns a tensor for statistics collection by a node.
        graph: Graph to set its tensors.
        qc: Quantization configuration containing parameters for how the graph should be quantized.

    """
    nodes_sorted = topological_sort(graph)
    for n in nodes_sorted:
        t = node_analyze_func(n, fw_info)  # Get tensor for the node
        # If we use bias correction, and the node has coefficients to quantize, we need to make sure
        # its previous nodes' tensors are consistent with this node.
        # TODO: factor tensor marking in case of bias correction.
        if qc.weights_bias_correction and fw_info.in_kernel_ops(n):
            for ie in graph.incoming_edges(n):
                input_node = ie.source_node
                create_tensor2node(graph,
                                   input_node)
        if t is not None:
            graph.set_out_stats_collector_to_node(n, t)