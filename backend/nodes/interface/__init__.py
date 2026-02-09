# Interface node types for the workflow interface builder.
# These nodes represent UI components that participate in workflow execution.

from nodes.interface.markdown_node import MarkdownInterfaceNode
from nodes.interface.image_node import ImageInterfaceNode

__all__ = [
    'MarkdownInterfaceNode',
    'ImageInterfaceNode',
]
