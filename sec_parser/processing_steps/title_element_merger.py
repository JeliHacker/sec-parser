from __future__ import annotations

from collections import deque
from typing import TYPE_CHECKING, cast

from sec_parser.processing_engine.html_tag import HtmlTag
from sec_parser.processing_steps.abstract_classes.abstract_element_batch_processing_step import (
    AbstractElementBatchProcessingStep,
)
from sec_parser.semantic_elements.abstract_semantic_element import (
    AbstractSemanticElement,
)
from sec_parser.semantic_elements.title_element import TitleElement

if TYPE_CHECKING:  # pragma: no cover
    from sec_parser.processing_steps.abstract_classes.processing_context import (
        ElementProcessingContext,
    )


class TitleElementMerger(AbstractElementBatchProcessingStep):
    """
    TitleElementMerger is a processing step that merges adjacent TitleElement instances
    that are on the same line. This addresses issues where section titles are split
    across multiple HTML elements (e.g., "PART I. FINANCI" and "AL INFORMATION").

    The merger identifies TitleElements with the same level that are:
    1. Adjacent in the element list
    2. On the same line (have the same parent HTML element)
    3. Have similar styling (optional heuristic)

    Example:
    -------
        Before: TitleElement("PART I. FINANCI") + TitleElement("AL INFORMATION")
        After:  TitleElement("PART I. FINANCIAL INFORMATION")

    """

    def _process_elements(
        self,
        elements: list[AbstractSemanticElement],
        _: ElementProcessingContext,
    ) -> list[AbstractSemanticElement]:
        result: deque[AbstractSemanticElement | None] = deque(elements)
        batch_indices: list[list[int]] = [[]]

        # Group adjacent TitleElements with the same level
        for i, element in enumerate(elements):
            if isinstance(element, TitleElement):
                # Check if this element can be merged with the previous batch
                if (batch_indices[-1] and
                    self._can_merge_with_batch(element, [elements[j] for j in batch_indices[-1]])):
                    batch_indices[-1].append(i)
                else:
                    # Start a new batch
                    if batch_indices[-1]:  # Only add new batch if previous one is not empty
                        batch_indices.append([])
                    batch_indices[-1].append(i)
            elif batch_indices[-1]:
                # Non-TitleElement breaks the batch
                batch_indices.append([])

        # Merge each batch
        for indices in batch_indices:
            if len(indices) <= 1:
                continue
            result[indices[0]] = self._merge(
                cast(
                    list[AbstractSemanticElement],
                    [result[i] for i in indices if result[i]],
                ),
            )
            for i in indices[1:]:
                result[i] = None

        return [element for element in result if element is not None]

    def _can_merge_with_batch(
        self,
        element: TitleElement,
        batch_elements: list[AbstractSemanticElement],
    ) -> bool:
        """Check if a TitleElement can be merged with a batch of elements."""
        if not batch_elements:
            return True

        # All elements in batch must be TitleElements
        if not all(isinstance(e, TitleElement) for e in batch_elements):
            return False

        # Check if all elements have the same level
        batch_level = batch_elements[0].level
        if element.level != batch_level:
            return False

        # Check if elements are on the same line (same parent)
        batch_parent = batch_elements[0].html_tag.parent
        element_parent = element.html_tag.parent

        if batch_parent is None or element_parent is None:
            return False

        # Elements are on the same line if they have the same parent
        if batch_parent._bs4 != element_parent._bs4:  # noqa: SLF001
            return False

        # Additional check: Don't merge sibling div elements that are separate titles
        # This prevents merging of separate title divs that happen to be siblings
        batch_tag = batch_elements[0].html_tag
        element_tag = element.html_tag

        # Only apply this check to div elements (not span elements)
        # Span elements are typically used for split titles that should be merged
        # Div elements are typically used for separate titles that should not be merged
        if (batch_tag.name == "div" and element_tag.name == "div" and
            batch_parent._bs4 == element_parent._bs4):  # noqa: SLF001

            # For div elements that are siblings, check if they represent separate titles
            batch_text = batch_elements[0].text.strip()
            element_text = element.text.strip()

            # If both texts appear to be complete, independent titles, don't merge them
            # This prevents cases like "Components of Results of Operations" + "Revenue"
            # from being merged into "Components of Results of OperationsRevenue"
            if batch_text and element_text:
                # Check if both texts appear to be complete, independent titles
                # For single words, we need them to be reasonably long to be considered complete titles
                # For multi-word phrases, they are likely complete titles
                min_single_word_length = 5
                batch_is_substantial = len(batch_text.split()) > 1 or len(batch_text) > min_single_word_length
                element_is_substantial = len(element_text.split()) > 1 or len(element_text) > min_single_word_length

                # Additional check: if both texts are substantial AND they don't appear to be
                # part of a split title (i.e., they don't end/start with incomplete words),
                # then they are likely separate titles that should not be merged
                if (batch_is_substantial and element_is_substantial and
                    batch_text and batch_text[-1].isalpha() and
                    element_text and element_text[0].isalpha()):
                    return False

        return True

    @classmethod
    def _merge(
        cls,
        elements: list[AbstractSemanticElement],
    ) -> AbstractSemanticElement:
        """Merge multiple TitleElements into a single TitleElement."""
        if not elements:
            msg = "Cannot merge empty list of elements"
            raise ValueError(msg)

        if len(elements) == 1:
            return elements[0]

        # All elements should be TitleElements
        title_elements = [cast(TitleElement, e) for e in elements]

        # Create a new HTML tag that wraps all the merged elements
        new_tag = HtmlTag.wrap_tags_in_new_parent(
            "sec-parser-merged-title",
            [e.html_tag for e in title_elements],
        )

        # Use the processing log from the first element
        merged_processing_log = title_elements[0].processing_log.copy()

        # Add a log entry about the merging
        merged_processing_log.add_item(
            message=f"Merged {len(title_elements)} TitleElements: {[e.text for e in title_elements]}",
            log_origin=cls.__name__,
        )

        # Create the merged TitleElement with the same level as the first element
        return TitleElement(
            new_tag,
            processing_log=merged_processing_log,
            level=title_elements[0].level,
            log_origin=cls.__name__,
        )

