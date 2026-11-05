from __future__ import annotations

import asyncio
import html
import math
from collections.abc import Callable
from datetime import date, datetime
from functools import partial
from typing import Any, cast

from PySide6.QtCore import QDate, QPointF, QRectF, Qt, QThread, QTimer, Signal
from PySide6.QtGui import (
    QBrush,
    QColor,
    QCursor,
    QFont,
    QFontMetrics,
    QPainter,
    QPainterPath,
    QPainterPathStroker,
    QPen,
    QPolygonF,
    QWheelEvent,
)
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDateEdit,
    QFrame,
    QGraphicsItem,
    QGraphicsScene,
    QGraphicsView,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSplitter,
    QStackedWidget,
    QTabWidget,
    QTextBrowser,
    QTextEdit,
    QToolButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from pactlyn.app.bootstrap import AppContainer
from pactlyn.memory.graph import (
    GraphEdge,
    GraphEdgeKind,
    GraphFilter,
    GraphNode,
    GraphNodeKind,
    GraphRecord,
    GraphTimelineItem,
    KnowledgeGraph,
    KnowledgeGraphRepository,
)
from pactlyn.memory.semantic import SemanticMemoryHit, SemanticMemorySearch
from pactlyn.ui.theme import (
    COLOR_TERRACOTTA,
    DARK_BG,
    DARK_CARD_BG,
    LIGHT_BG,
    LIGHT_CARD_BG,
    ThemeMode,
    get_saved_theme,
)

NODE_WIDTH = 220.0
NODE_HEIGHT = 76.0
NODE_GAP_X = 84.0
NODE_GAP_Y = 24.0

NODE_TITLES: dict[GraphNodeKind, str] = {
    GraphNodeKind.PERSON: "Person",
    GraphNodeKind.COMMITMENT: "Commitment",
    GraphNodeKind.PROJECT: "Project",
    GraphNodeKind.EMAIL: "Email",
    GraphNodeKind.EVENT: "Event",
    GraphNodeKind.DOCUMENT: "Document",
    GraphNodeKind.MEMORY: "Memory",
    GraphNodeKind.PERSONAL_FACT: "Personal Fact",
}

NODE_ICONS: dict[GraphNodeKind, str] = {
    GraphNodeKind.PERSON: "👤",
    GraphNodeKind.COMMITMENT: "✓",
    GraphNodeKind.PROJECT: "▣",
    GraphNodeKind.EMAIL: "✉",
    GraphNodeKind.EVENT: "◷",
    GraphNodeKind.DOCUMENT: "▤",
    GraphNodeKind.MEMORY: "✦",
    GraphNodeKind.PERSONAL_FACT: "★",
}

NODE_STYLES: dict[ThemeMode, dict[GraphNodeKind, tuple[str, str, str]]] = {
    "light": {
        GraphNodeKind.PERSON: ("#E4F1EB", "#4C8875", "#1E5242"),
        GraphNodeKind.COMMITMENT: ("#E8EEFB", "#5474C8", "#263F7A"),
        GraphNodeKind.PROJECT: ("#F0ECE2", "#9B8B70", "#5D5040"),
        GraphNodeKind.EMAIL: ("#F1E9F7", "#8A67B5", "#4F346E"),
        GraphNodeKind.EVENT: ("#FBEDE3", "#C66F50", "#7D3E27"),
        GraphNodeKind.DOCUMENT: ("#EFF1F3", "#8B949E", "#48515A"),
        GraphNodeKind.MEMORY: ("#F5F0E4", "#B09A61", "#66552C"),
        GraphNodeKind.PERSONAL_FACT: ("#E6F4F8", "#3A90B4", "#1A5470"),
    },
    "dark": {
        GraphNodeKind.PERSON: ("#183A33", "#4E9A84", "#D6EFE7"),
        GraphNodeKind.COMMITMENT: ("#1B2B4B", "#6C8BD7", "#DCE5FA"),
        GraphNodeKind.PROJECT: ("#302B24", "#B7A789", "#F0E6D4"),
        GraphNodeKind.EMAIL: ("#30243F", "#A987D1", "#EBDCFA"),
        GraphNodeKind.EVENT: ("#3B271F", "#D27C5C", "#FBE5DA"),
        GraphNodeKind.DOCUMENT: ("#252B30", "#9CA8B3", "#E4EAEE"),
        GraphNodeKind.MEMORY: ("#322E23", "#C0AB70", "#F4EACB"),
        GraphNodeKind.PERSONAL_FACT: ("#162832", "#4CAED4", "#C8EAF5"),
    },
}

EDGE_STYLES: dict[ThemeMode, dict[GraphEdgeKind, str]] = {
    "light": {
        GraphEdgeKind.BLOCKED_BY: "#B05C3F",
        GraphEdgeKind.DEPENDS_ON: "#C66F50",
        GraphEdgeKind.FOLLOWED_BY: "#3F7C69",
        GraphEdgeKind.RESPONSE_REQUIRED_FROM: "#A8792F",
        GraphEdgeKind.RELATED_TO: "#7A8780",
        GraphEdgeKind.SUPERSEDES: "#7B688C",
        GraphEdgeKind.PERSON_PERFORMS_ACTION: "#3F7C69",
        GraphEdgeKind.PERSON_RECEIVES_EMAIL: "#8A67B5",
        GraphEdgeKind.PERSON_SENT_EMAIL: "#8A67B5",
        GraphEdgeKind.EMAIL_RELATES_TO_COMMITMENT: "#8A67B5",
        GraphEdgeKind.CONTACT_ASSOCIATED_WITH_PROJECT: "#7A8780",
        GraphEdgeKind.HAS_EVENT: "#B77A5A",
        GraphEdgeKind.HAS_ATTACHMENT: "#8B949E",
        GraphEdgeKind.HAS_MEMORY: "#A08A51",
        GraphEdgeKind.HAS_BIRTHDAY: "#3A90B4",
        GraphEdgeKind.HAS_IDENTITY: "#3A90B4",
        GraphEdgeKind.STUDIES_AT: "#3A90B4",
        GraphEdgeKind.WORKS_ON: "#3A90B4",
        GraphEdgeKind.PREFERS: "#3A90B4",
        GraphEdgeKind.HAS_CONTACT_INFO: "#3A90B4",
        GraphEdgeKind.HAS_PERSONAL_FACT: "#3A90B4",
    },
    "dark": {
        GraphEdgeKind.BLOCKED_BY: "#D27C5C",
        GraphEdgeKind.DEPENDS_ON: "#D98A69",
        GraphEdgeKind.FOLLOWED_BY: "#63B098",
        GraphEdgeKind.RESPONSE_REQUIRED_FROM: "#D4AB63",
        GraphEdgeKind.RELATED_TO: "#9AA9A2",
        GraphEdgeKind.SUPERSEDES: "#AE9BC0",
        GraphEdgeKind.PERSON_PERFORMS_ACTION: "#63B098",
        GraphEdgeKind.PERSON_RECEIVES_EMAIL: "#B394D8",
        GraphEdgeKind.PERSON_SENT_EMAIL: "#B394D8",
        GraphEdgeKind.EMAIL_RELATES_TO_COMMITMENT: "#B394D8",
        GraphEdgeKind.CONTACT_ASSOCIATED_WITH_PROJECT: "#9AA9A2",
        GraphEdgeKind.HAS_EVENT: "#D69A7A",
        GraphEdgeKind.HAS_ATTACHMENT: "#AAB5BE",
        GraphEdgeKind.HAS_MEMORY: "#C0AA6F",
        GraphEdgeKind.HAS_BIRTHDAY: "#4CAED4",
        GraphEdgeKind.HAS_IDENTITY: "#4CAED4",
        GraphEdgeKind.STUDIES_AT: "#4CAED4",
        GraphEdgeKind.WORKS_ON: "#4CAED4",
        GraphEdgeKind.PREFERS: "#4CAED4",
        GraphEdgeKind.HAS_CONTACT_INFO: "#4CAED4",
        GraphEdgeKind.HAS_PERSONAL_FACT: "#4CAED4",
    },
}

STATUS_OPTIONS: list[tuple[str, str | None]] = [
    ("All statuses", None),
    ("Active", "active"),
    ("Waiting", "waiting"),
    ("Blocked", "blocked"),
    ("Overdue", "overdue"),
    ("Completed", "completed"),
    ("Cancelled", "cancelled"),
]

RELATIONSHIP_OPTIONS: list[tuple[str, str | None]] = [
    ("All relationships", None),
    ("Dependencies", "dependencies"),
    ("Waiting-for", "waiting"),
    ("Follow-ups", "follow_ups"),
    ("Superseded", "superseded"),
    ("Personal facts", "personal_facts"),
    ("General associations", "associations"),
]

FILTER_NODE_KINDS: list[tuple[GraphNodeKind, str]] = [
    (GraphNodeKind.PERSON, "People"),
    (GraphNodeKind.COMMITMENT, "Commitments"),
    (GraphNodeKind.PERSONAL_FACT, "Personal Facts"),
    (GraphNodeKind.PROJECT, "Projects"),
    (GraphNodeKind.EMAIL, "Emails"),
    (GraphNodeKind.EVENT, "Events"),
    (GraphNodeKind.DOCUMENT, "Documents"),
    (GraphNodeKind.MEMORY, "Memories"),
]

LAYOUTED_EDGE_KINDS = frozenset(
    {
        GraphEdgeKind.BLOCKED_BY,
        GraphEdgeKind.DEPENDS_ON,
        GraphEdgeKind.FOLLOWED_BY,
        GraphEdgeKind.RESPONSE_REQUIRED_FROM,
        GraphEdgeKind.SUPERSEDES,
    }
)


def _node_style(kind: GraphNodeKind, mode: ThemeMode) -> tuple[str, str, str]:
    return NODE_STYLES[mode][kind]


def _edge_color(kind: GraphEdgeKind, mode: ThemeMode) -> str:
    return EDGE_STYLES[mode][kind]


def _truncate(value: str, limit: int) -> str:
    text = " ".join(value.split())
    if len(text) <= limit:
        return text
    return f"{text[: limit - 1].rstrip()}…"


def _format_date(value: datetime | None) -> str:
    if value is None:
        return "Undated"
    if value.tzinfo is not None:
        value = value.astimezone()
    return value.strftime("%d %b %Y")


def _format_time(value: datetime | None) -> str:
    if value is None:
        return "—"
    if value.tzinfo is not None:
        value = value.astimezone()
    return value.strftime("%H:%M")


def _format_datetime(value: datetime | None) -> str:
    if value is None:
        return "Not recorded"
    if value.tzinfo is not None:
        value = value.astimezone()
    return value.strftime("%d %b %Y, %H:%M")


def _safe(value: object) -> str:
    return html.escape(str(value)).replace("\n", "<br>")


def _edge_review_label(edge: GraphEdge) -> str:
    status = edge.validation_status.strip().lower()
    if status == "validated":
        return "Validated relationship"
    if status == "reviewed":
        return "Reviewed association"
    if status == "needs_review":
        return "Awaiting review"
    if status == "rejected":
        return "Rejected"
    if edge.origin == "commitment_relationship":
        return "Inferred relationship"
    return "Derived from stored record"


class GraphNodeItem(QGraphicsItem):
    def __init__(self, node: GraphNode, mode: ThemeMode):
        super().__init__()
        self.node = node
        self.mode = mode
        self.edges: set[GraphEdgeItem] = set()
        self._hovered = False
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable, True)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, True)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges, True)
        self.setAcceptHoverEvents(True)
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.setCacheMode(QGraphicsItem.CacheMode.DeviceCoordinateCache)
        self.setZValue(2)
        self.setToolTip(f"{node.label}\n{node.subtitle}")

    def boundingRect(self) -> QRectF:  # noqa: N802
        return QRectF(0.0, 0.0, NODE_WIDTH, NODE_HEIGHT)

    def center(self) -> QPointF:
        return self.pos() + QPointF(NODE_WIDTH / 2, NODE_HEIGHT / 2)

    def paint(self, painter: QPainter, _option: Any, _widget: QWidget | None = None) -> None:
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        fill, border, foreground = _node_style(self.node.kind, self.mode)
        selected = self.isSelected()
        if selected:
            border = COLOR_TERRACOTTA
        elif self._hovered:
            border = QColor(border).lighter(108).name()
        shadow = QColor(0, 0, 0, 34 if self.mode == "light" else 70)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(shadow)
        painter.drawRoundedRect(QRectF(2.0, 3.0, NODE_WIDTH, NODE_HEIGHT), 13.0, 13.0)
        painter.setBrush(QBrush(QColor(fill)))
        painter.setPen(QPen(QColor(border), 2.2 if selected else 1.1))
        painter.drawRoundedRect(QRectF(0.0, 0.0, NODE_WIDTH, NODE_HEIGHT), 13.0, 13.0)

        icon_rect = QRectF(14.0, 21.0, 32.0, 32.0)
        painter.setBrush(QBrush(QColor(border)))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(icon_rect)
        icon_font = QFont()
        icon_font.setPointSizeF(13.0)
        icon_font.setBold(True)
        painter.setFont(icon_font)
        painter.setPen(QColor("#FFFFFF"))
        painter.drawText(
            icon_rect,
            int(Qt.AlignmentFlag.AlignCenter),
            NODE_ICONS[self.node.kind],
        )

        title_font = QFont()
        title_font.setPointSizeF(10.5)
        title_font.setBold(True)
        painter.setFont(title_font)
        painter.setPen(QColor(foreground))
        title_metrics = QFontMetrics(title_font)
        title = title_metrics.elidedText(
            self.node.label,
            Qt.TextElideMode.ElideRight,
            int(NODE_WIDTH - 78),
        )
        painter.drawText(
            QRectF(56.0, 13.0, NODE_WIDTH - 74.0, 22.0),
            int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
            title,
        )

        subtitle_font = QFont()
        subtitle_font.setPointSizeF(8.7)
        painter.setFont(subtitle_font)
        painter.setPen(QColor(border))
        subtitle_metrics = QFontMetrics(subtitle_font)
        subtitle = subtitle_metrics.elidedText(
            self.node.subtitle,
            Qt.TextElideMode.ElideRight,
            int(NODE_WIDTH - 78.0),
        )
        painter.drawText(
            QRectF(56.0, 37.0, NODE_WIDTH - 74.0, 20.0),
            int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
            subtitle,
        )

        if self.node.warning:
            badge = QRectF(NODE_WIDTH - 24.0, 9.0, 15.0, 15.0)
            painter.setBrush(QBrush(QColor(COLOR_TERRACOTTA)))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawEllipse(badge)
            badge_font = QFont()
            badge_font.setPointSizeF(8.0)
            badge_font.setBold(True)
            painter.setFont(badge_font)
            painter.setPen(QColor("#FFFFFF"))
            painter.drawText(badge, int(Qt.AlignmentFlag.AlignCenter), "!")
        elif self.node.completed:
            badge = QRectF(NODE_WIDTH - 24.0, 9.0, 15.0, 15.0)
            painter.setBrush(QBrush(QColor("#3F7C69" if self.mode == "light" else "#63B098")))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawEllipse(badge)
            badge_font = QFont()
            badge_font.setPointSizeF(8.0)
            badge_font.setBold(True)
            painter.setFont(badge_font)
            painter.setPen(QColor("#FFFFFF"))
            painter.drawText(badge, int(Qt.AlignmentFlag.AlignCenter), "✓")

    def itemChange(self, change: QGraphicsItem.GraphicsItemChange, value: Any) -> Any:  # noqa: N802
        if change == QGraphicsItem.GraphicsItemChange.ItemPositionHasChanged:
            for edge in self.edges:
                edge.update_path()
        return super().itemChange(change, value)

    def hoverEnterEvent(self, event: Any) -> None:  # noqa: N802
        self._hovered = True
        self.update()
        super().hoverEnterEvent(event)

    def hoverLeaveEvent(self, event: Any) -> None:  # noqa: N802
        self._hovered = False
        self.update()
        super().hoverLeaveEvent(event)


class GraphEdgeItem(QGraphicsItem):
    def __init__(
        self,
        edge: GraphEdge,
        source: GraphNodeItem,
        target: GraphNodeItem,
        mode: ThemeMode,
        *,
        parallel: int = 0,
    ):
        super().__init__()
        self.edge = edge
        self.source = source
        self.target = target
        self.mode = mode
        self.parallel = parallel
        self._path = QPainterPath()
        self._label_rect = QRectF()
        self._label_point = QPointF()
        self._arrow = QPolygonF()
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, True)
        self.setAcceptedMouseButtons(Qt.MouseButton.LeftButton)
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.setZValue(1)
        self.setToolTip(f"{edge.label}: {source.node.label} → {target.node.label}")
        self.update_path()

    def boundingRect(self) -> QRectF:  # noqa: N802
        return self._path.boundingRect().united(self._label_rect).adjusted(-24, -24, 24, 24)

    def shape(self) -> QPainterPath:
        stroker = QPainterPathStroker()
        stroker.setWidth(16.0)
        shape = stroker.createStroke(self._path)
        shape.addRect(self._label_rect)
        return shape

    def update_path(self) -> None:
        self.prepareGeometryChange()
        start = self._edge_point(self.source.sceneBoundingRect(), self.target.center())
        end = self._edge_point(self.target.sceneBoundingRect(), self.source.center())
        dx = end.x() - start.x()
        dy = end.y() - start.y()
        length = math.hypot(dx, dy) or 1.0
        perpendicular = QPointF(-dy / length, dx / length)
        offset = (self.parallel % 3) * 18.0
        midpoint = QPointF((start.x() + end.x()) / 2, (start.y() + end.y()) / 2)
        control = midpoint + perpendicular * (14.0 + offset)
        path = QPainterPath(start)
        path.quadTo(control, end)
        self._path = path
        self._label_point = midpoint + perpendicular * (7.0 + offset * 0.4)
        arrow_angle = math.atan2(end.y() - control.y(), end.x() - control.x())
        arrow_size = 10.0
        self._arrow = QPolygonF(
            [
                end,
                end
                + QPointF(
                    -math.cos(arrow_angle - 0.48) * arrow_size,
                    -math.sin(arrow_angle - 0.48) * arrow_size,
                ),
                end
                + QPointF(
                    -math.cos(arrow_angle + 0.48) * arrow_size,
                    -math.sin(arrow_angle + 0.48) * arrow_size,
                ),
            ]
        )
        label_font = QFont()
        label_font.setPointSizeF(8.2)
        metrics = QFontMetrics(label_font)
        label_text = self.edge.label
        label_width = metrics.horizontalAdvance(label_text) + 14
        label_height = metrics.height() + 6
        self._label_rect = QRectF(
            self._label_point.x() - label_width / 2,
            self._label_point.y() - label_height / 2,
            label_width,
            label_height,
        )

    @staticmethod
    def _edge_point(rect: QRectF, toward: QPointF) -> QPointF:
        center = rect.center()
        dx = toward.x() - center.x()
        dy = toward.y() - center.y()
        if dx == 0 and dy == 0:
            return center
        half_width = rect.width() / 2
        half_height = rect.height() / 2
        scale_x = half_width / abs(dx) if dx else math.inf
        scale_y = half_height / abs(dy) if dy else math.inf
        scale = min(scale_x, scale_y)
        return QPointF(center.x() + dx * scale, center.y() + dy * scale)

    def paint(self, painter: QPainter, _option: Any, _widget: QWidget | None = None) -> None:
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        color = QColor(
            COLOR_TERRACOTTA if self.isSelected() else _edge_color(self.edge.kind, self.mode)
        )
        width = 3.0 if self.isSelected() else 1.8
        pen = QPen(color, width)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(self._path)
        painter.setBrush(QBrush(color))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawPolygon(self._arrow)

        scale = 1.0
        scene = self.scene()
        if scene is not None and scene.views():
            scale = scene.views()[0].transform().m11()
        if scale < 0.45:
            return
        label_font = QFont()
        label_font.setPointSizeF(8.2)
        label_font.setBold(self.isSelected())
        painter.setFont(label_font)
        background = QColor(DARK_CARD_BG if self.mode == "dark" else LIGHT_CARD_BG)
        background.setAlpha(232)
        painter.setBrush(QBrush(background))
        painter.setPen(QPen(color, 1.0))
        painter.drawRoundedRect(self._label_rect, 6.0, 6.0)
        painter.setPen(color)
        painter.drawText(
            self._label_rect,
            int(Qt.AlignmentFlag.AlignCenter),
            self.edge.label,
        )

    def mousePressEvent(self, event: Any) -> None:  # noqa: N802
        self.scene().clearSelection()
        self.setSelected(True)
        event.accept()


class GraphCanvas(QGraphicsView):
    nodeSelected = Signal(str)
    edgeSelected = Signal(str)
    selectionCleared = Signal()

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._graph = KnowledgeGraph()
        self._mode: ThemeMode = get_saved_theme()
        self._filter = GraphFilter()
        self._node_items: dict[str, GraphNodeItem] = {}
        self._edge_items: dict[str, GraphEdgeItem] = {}
        self._positions: dict[str, QPointF] = {}
        self._hidden_nodes: set[str] = set()
        self._highlight_node: str | None = None
        self._highlight_mode: str | None = None
        self._layout_mode = "auto"
        self._scene = QGraphicsScene(self)
        self.setScene(self._scene)
        self.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        self.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorViewCenter)
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setMinimumHeight(420)
        self._apply_background()
        self._scene.selectionChanged.connect(self._on_selection_changed)

    @property
    def graph(self) -> KnowledgeGraph:
        return self._graph

    @property
    def layout_mode(self) -> str:
        return self._layout_mode

    @property
    def visible_node_count(self) -> int:
        return sum(1 for item in self._node_items.values() if item.isVisible())

    @property
    def visible_edge_count(self) -> int:
        return sum(1 for item in self._edge_items.values() if item.isVisible())

    def set_theme(self, mode: ThemeMode) -> None:
        self._mode = mode
        self._apply_background()
        for item in self._node_items.values():
            item.mode = mode
            item.update()
        for edge in self._edge_items.values():
            edge.mode = mode
            edge.update()

    def _apply_background(self) -> None:
        background = DARK_BG if self._mode == "dark" else LIGHT_BG
        self._scene.setBackgroundBrush(QBrush(QColor(background)))
        self.viewport().update()

    def set_graph(self, graph: KnowledgeGraph, *, fit: bool = True) -> None:
        saved_positions = {
            node_id: item.pos()
            for node_id, item in self._node_items.items()
            if node_id in {node.id for node in graph.nodes}
        }
        self._graph = graph
        self._scene.clear()
        self._node_items = {}
        self._edge_items = {}
        for node in graph.nodes:
            item = GraphNodeItem(node, self._mode)
            self._scene.addItem(item)
            self._node_items[node.id] = item
        pair_counts: dict[tuple[str, str], int] = {}
        for edge in graph.edges:
            source = self._node_items.get(edge.source_id)
            target = self._node_items.get(edge.target_id)
            if source is None or target is None:
                continue
            pair = (
                (edge.source_id, edge.target_id)
                if edge.source_id <= edge.target_id
                else (edge.target_id, edge.source_id)
            )
            parallel = pair_counts.get(pair, 0)
            pair_counts[pair] = parallel + 1
            edge_item = GraphEdgeItem(
                edge, source, target, self._mode, parallel=parallel
            )
            self._scene.addItem(edge_item)
            self._edge_items[edge.id] = edge_item
            source.edges.add(edge_item)
            target.edges.add(edge_item)
        layout = self._compute_layout(graph)
        layout.update(saved_positions)
        for node_id, item in self._node_items.items():
            position = layout.get(node_id, QPointF(0.0, 0.0))
            item.setPos(position)
            self._positions[node_id] = position
        valid_ids = set(self._node_items)
        self._positions = {
            node_id: position
            for node_id, position in self._positions.items()
            if node_id in valid_ids
        }
        self._hidden_nodes &= valid_ids
        self.apply_filters()
        if fit:
            self.fit_graph()

    def _compute_layout(self, graph: KnowledgeGraph) -> dict[str, QPointF]:
        if not graph.nodes:
            return {}
        mode = self._layout_mode
        if mode == "auto":
            dependency_count = sum(
                1 for edge in graph.edges if edge.kind in LAYOUTED_EDGE_KINDS
            )
            commitment_count = sum(
                1 for node in graph.nodes if node.kind == GraphNodeKind.COMMITMENT
            )
            mode = (
                "layered"
                if dependency_count >= 4 and commitment_count <= 40
                else "relationship"
            )
        if mode == "layered":
            return self._layered_layout(graph)
        return self._relationship_layout(graph)

    def _layered_layout(self, graph: KnowledgeGraph) -> dict[str, QPointF]:
        commitment_nodes = [
            node for node in graph.nodes if node.kind == GraphNodeKind.COMMITMENT
        ]
        layers = {node.id: 0 for node in commitment_nodes}
        dependency_edges = [
            edge for edge in graph.edges if edge.kind in LAYOUTED_EDGE_KINDS
        ]
        for _iteration in range(min(max(len(commitment_nodes), 1), 20)):
            changed = False
            for edge in dependency_edges:
                if edge.source_id in layers and edge.target_id in layers:
                    candidate = min(layers[edge.source_id] + 1, 20)
                    if candidate > layers[edge.target_id]:
                        layers[edge.target_id] = candidate
                        changed = True
            if not changed:
                break
        layer_values = sorted(set(layers.values()))
        layer_columns = {layer: index + 1 for index, layer in enumerate(layer_values)}
        right_column = max(layer_columns.values(), default=0) + 1
        columns: dict[int, list[GraphNode]] = {}
        for node in graph.nodes:
            if node.kind == GraphNodeKind.COMMITMENT:
                column = layer_columns.get(layers.get(node.id, 0), 1)
            elif node.kind in {GraphNodeKind.PERSON, GraphNodeKind.MEMORY, GraphNodeKind.PERSONAL_FACT}:
                column = 0
            else:
                column = right_column
            columns.setdefault(column, []).append(node)
        return self._place_columns(columns)

    @staticmethod
    def _place_columns(columns: dict[int, list[GraphNode]]) -> dict[str, QPointF]:
        positions: dict[str, QPointF] = {}
        for column, nodes in sorted(columns.items()):
            nodes.sort(key=lambda node: (node.kind.value, node.label.casefold(), node.id))
            total_height = len(nodes) * (NODE_HEIGHT + NODE_GAP_Y) - NODE_GAP_Y
            start_y = -total_height / 2
            x = column * (NODE_WIDTH + NODE_GAP_X)
            for index, node in enumerate(nodes):
                positions[node.id] = QPointF(
                    x,
                    start_y + index * (NODE_HEIGHT + NODE_GAP_Y),
                )
        return positions

    def _relationship_layout(self, graph: KnowledgeGraph) -> dict[str, QPointF]:
        nodes = list(graph.nodes)
        if not nodes:
            return {}
        by_kind: dict[GraphNodeKind, list[GraphNode]] = {}
        for node in nodes:
            by_kind.setdefault(node.kind, []).append(node)
        groups: list[list[GraphNodeKind]] = [
            [GraphNodeKind.PERSON, GraphNodeKind.MEMORY, GraphNodeKind.PERSONAL_FACT],
            [GraphNodeKind.PROJECT, GraphNodeKind.COMMITMENT],
            [GraphNodeKind.EMAIL, GraphNodeKind.EVENT, GraphNodeKind.DOCUMENT],
        ]
        columns: list[list[GraphNode]] = []
        for group in groups:
            group_nodes = sorted(
                [node for kind in group for node in by_kind.get(kind, [])],
                key=lambda node: (node.kind.value, node.label.casefold(), node.id),
            )
            if group_nodes:
                columns.append(group_nodes)
        if not columns:
            return {}

        initial: dict[str, tuple[int, int]] = {}
        positions: dict[str, QPointF] = {}
        for column, group_nodes in enumerate(columns):
            for row, node in enumerate(group_nodes):
                initial[node.id] = (column, row)
                positions[node.id] = QPointF(
                    column * (NODE_WIDTH + NODE_GAP_X),
                    row * (NODE_HEIGHT + NODE_GAP_Y),
                )

        neighbours: dict[str, set[str]] = {node.id: set() for node in nodes}
        for edge in graph.edges:
            if edge.source_id in neighbours and edge.target_id in neighbours:
                neighbours[edge.source_id].add(edge.target_id)
                neighbours[edge.target_id].add(edge.source_id)

        def place(column_index: int) -> None:
            group_nodes = columns[column_index]

            def sort_key(node: GraphNode) -> tuple[float, int, str, str, str]:
                other_y = [
                    positions[other].y()
                    for other in neighbours[node.id]
                    if other in initial and initial[other][0] != column_index
                ]
                anchor = sum(other_y) / len(other_y) if other_y else 0.0
                return (
                    anchor,
                    initial[node.id][1],
                    node.kind.value,
                    node.label.casefold(),
                    node.id,
                )

            group_nodes.sort(key=sort_key)
            total_height = len(group_nodes) * (NODE_HEIGHT + NODE_GAP_Y) - NODE_GAP_Y
            start_y = -total_height / 2
            x = column_index * (NODE_WIDTH + NODE_GAP_X)
            for row, node in enumerate(group_nodes):
                positions[node.id] = QPointF(
                    x,
                    start_y + row * (NODE_HEIGHT + NODE_GAP_Y),
                )

        for _iteration in range(3):
            for index in range(1, len(columns)):
                place(index)
            if len(columns) > 1:
                place(0)

        min_y = min(position.y() for position in positions.values())
        return {
            node_id: QPointF(position.x(), position.y() - min_y)
            for node_id, position in positions.items()
        }

    def reset_layout(self) -> None:
        if not self._graph.nodes:
            return
        self._positions = {}
        layout = self._compute_layout(self._graph)
        for node_id, item in self._node_items.items():
            position = layout.get(node_id, QPointF(0.0, 0.0))
            item.setPos(position)
            self._positions[node_id] = position
        self.fit_graph()

    def set_layout_mode(self, mode: str) -> None:
        if mode not in {"auto", "layered", "relationship"}:
            return
        self._layout_mode = mode
        self.reset_layout()

    def fit_graph(self) -> None:
        if not self._node_items:
            return
        bounds = self._scene.itemsBoundingRect()
        if bounds.isNull():
            return
        self.resetTransform()
        self.fitInView(
            bounds.adjusted(-60, -60, 60, 60),
            Qt.AspectRatioMode.KeepAspectRatio,
        )
        scale = self.transform().m11()
        if scale > 1.15:
            self.scale(1.15 / scale, 1.15 / scale)
        elif scale < 0.14:
            self.scale(0.14 / scale, 0.14 / scale)

    def zoom_in(self) -> None:
        if self.transform().m11() < 3.0:
            self.scale(1.18, 1.18)

    def zoom_out(self) -> None:
        if self.transform().m11() > 0.14:
            self.scale(1 / 1.18, 1 / 1.18)

    def wheelEvent(self, event: QWheelEvent) -> None:  # noqa: N802
        if event.angleDelta().y() == 0:
            super().wheelEvent(event)
            return
        self.zoom_in() if event.angleDelta().y() > 0 else self.zoom_out()
        event.accept()

    def set_filter(self, graph_filter: GraphFilter) -> None:
        self._filter = graph_filter
        self.apply_filters()

    def apply_filters(self) -> None:
        available = {node.id for node in self._graph.nodes}
        self._hidden_nodes &= available
        visible_nodes = {
            node.id
            for node in self._graph.nodes
            if self._filter.allows_node(node)
            and node.id not in self._hidden_nodes
        }
        for node_id, item in self._node_items.items():
            item.setVisible(node_id in visible_nodes)
        for edge in self._graph.edges:
            edge_item = self._edge_items.get(edge.id)
            if edge_item is None:
                continue
            edge_item.setVisible(
                edge.source_id in visible_nodes
                and edge.target_id in visible_nodes
                and self._filter.allows_edge(edge)
            )
        selected = self.selected_node_id()
        if selected and selected not in visible_nodes:
            self._scene.clearSelection()
        self._apply_highlight()

    def selected_node_id(self) -> str | None:
        for item in self._scene.selectedItems():
            if isinstance(item, GraphNodeItem):
                return item.node.id
        return None

    def selected_edge_id(self) -> str | None:
        for item in self._scene.selectedItems():
            if isinstance(item, GraphEdgeItem):
                return item.edge.id
        return None

    def focus_node(self, node_id: str, *, center: bool = True) -> bool:
        item = self._node_items.get(node_id)
        if item is None:
            return False
        self._hidden_nodes.discard(node_id)
        self.apply_filters()
        self._scene.clearSelection()
        item.setSelected(True)
        if center:
            self.centerOn(item)
        return True

    def focus_edge(self, edge_id: str, *, center: bool = True) -> bool:
        item = self._edge_items.get(edge_id)
        if item is None:
            return False
        self._scene.clearSelection()
        item.setSelected(True)
        if center:
            self.centerOn(item)
        return True

    def clear_selection(self) -> None:
        self._scene.clearSelection()

    def collapse_selected(self) -> bool:
        node_id = self.selected_node_id()
        if not node_id:
            return False
        neighbours = {
            edge.target_id if edge.source_id == node_id else edge.source_id
            for edge in self._graph.edges_for(node_id)
        }
        if not neighbours:
            return False
        self._hidden_nodes.update(neighbours)
        self.apply_filters()
        return True

    def expand_selected(self) -> bool:
        node_id = self.selected_node_id()
        if not node_id:
            return False
        neighbours = {
            edge.target_id if edge.source_id == node_id else edge.source_id
            for edge in self._graph.edges_for(node_id)
        }
        before = set(self._hidden_nodes)
        self._hidden_nodes.difference_update(neighbours)
        self.apply_filters()
        return self._hidden_nodes != before

    def highlight(self, mode: str) -> bool:
        node_id = self.selected_node_id()
        if not node_id or mode not in {"in", "out", "neighbours"}:
            return False
        self._highlight_node = node_id
        self._highlight_mode = mode
        self._apply_highlight()
        return True

    def clear_highlight(self) -> None:
        self._highlight_node = None
        self._highlight_mode = None
        for node_item in self._node_items.values():
            node_item.setOpacity(1.0)
        for edge_item in self._edge_items.values():
            edge_item.setOpacity(1.0)

    def _apply_highlight(self) -> None:
        if not self._highlight_node or not self._highlight_mode:
            self.clear_highlight()
            return
        direction = {
            "in": "in",
            "out": "out",
            "neighbours": "both",
        }[self._highlight_mode]
        edges = self._graph.edges_for(
            self._highlight_node,
            direction=cast(Any, direction),
        )
        related_edges = {edge.id for edge in edges}
        related_nodes = {self._highlight_node}
        for edge in edges:
            related_nodes.add(edge.source_id)
            related_nodes.add(edge.target_id)
        for node_id, node_item in self._node_items.items():
            node_item.setOpacity(1.0 if node_id in related_nodes else 0.28)
        for edge_id, edge_item in self._edge_items.items():
            edge_item.setOpacity(1.0 if edge_id in related_edges else 0.16)

    def _on_selection_changed(self) -> None:
        node_id = self.selected_node_id()
        edge_id = self.selected_edge_id()
        if node_id:
            self._highlight_node = node_id
            self._highlight_mode = "neighbours"
            self._apply_highlight()
            self.nodeSelected.emit(node_id)
        elif edge_id:
            self.clear_highlight()
            self.edgeSelected.emit(edge_id)
        else:
            self.clear_highlight()
            self.selectionCleared.emit()


class DetailPanel(QWidget):
    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setMinimumWidth(310)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        title = QLabel("Details")
        title.setStyleSheet("font-weight: 700; font-size: 14px;")
        layout.addWidget(title)
        self.browser = QTextBrowser()
        self.browser.setOpenLinks(False)
        self.browser.setMinimumHeight(320)
        layout.addWidget(self.browser, 1)
        self.action_button = QPushButton()
        self.action_button.setObjectName("secondary")
        self.action_button.hide()
        layout.addWidget(self.action_button)
        self.dev_toggle = QToolButton()
        self.dev_toggle.setText("Developer details")
        self.dev_toggle.setCheckable(True)
        self.dev_toggle.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
        layout.addWidget(self.dev_toggle)
        self.dev_text = QTextEdit()
        self.dev_text.setReadOnly(True)
        self.dev_text.setMaximumHeight(170)
        self.dev_text.hide()
        layout.addWidget(self.dev_text)
        self.dev_toggle.toggled.connect(self.dev_text.setVisible)
        self.action_button.clicked.connect(self._run_action)
        self._action: Callable[[], None] | None = None
        self.show_content(
            "<p>Select a node or relationship to inspect it.</p>",
            "No technical metadata selected.",
        )

    def show_content(
        self,
        content_html: str,
        developer_text: str,
        *,
        action_label: str = "",
        action: Callable[[], None] | None = None,
    ) -> None:
        self.browser.setHtml(content_html)
        self.dev_text.setPlainText(developer_text or "No additional technical metadata.")
        self.dev_toggle.setChecked(False)
        self.dev_text.setVisible(False)
        self._action = action
        self.action_button.setText(action_label)
        self.action_button.setVisible(bool(action_label and action is not None))

    def _run_action(self) -> None:
        if self._action is not None:
            self._action()


class SemanticSearchWorker(QThread):
    """Run local Qdrant/embedding search without blocking the UI thread."""

    resultsReady = Signal(str, object)
    searchFailed = Signal(str, str)

    def __init__(
        self,
        container: AppContainer,
        query: str,
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self.container = container
        self.query = query

    def run(self) -> None:
        session = self.container.session()
        try:
            searcher = SemanticMemorySearch(
                session,
                self.container.vectors,
                self.container.embedder,
            )
            hits = asyncio.run(searcher.search(self.query))
        except Exception as exc:  # pragma: no cover - depends on local services
            self.searchFailed.emit(self.query, str(exc))
        else:
            self.resultsReady.emit(self.query, hits)
        finally:
            session.close()


class MemoryPage(QWidget):
    navigateRequested = Signal(str, str)
    createCommitmentRequested = Signal()

    def __init__(self, container: AppContainer, parent: QWidget | None = None):
        super().__init__(parent)
        self.container = container
        self._mode = get_saved_theme()
        self._graph = KnowledgeGraph()
        self._records_by_id: dict[str, GraphRecord] = {}
        self._timeline_items: tuple[GraphTimelineItem, ...] = ()
        self._has_loaded = False
        self._timeline_has_loaded = False
        self._timeline_min: date | None = None
        self._timeline_max: date | None = None
        self._stat_values: dict[str, QLabel] = {}
        self._semantic_hits: tuple[SemanticMemoryHit, ...] = ()
        self._semantic_query = ""
        self._semantic_worker: SemanticSearchWorker | None = None
        self._build_ui()
        self.refresh()

    @property
    def graph(self) -> KnowledgeGraph:
        return self._graph

    @property
    def canvas(self) -> GraphCanvas:
        return self.graph_canvas

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 24, 28, 24)
        layout.setSpacing(14)
        header = QHBoxLayout()
        title_box = QVBoxLayout()
        title = QLabel("Memory")
        title.setObjectName("title")
        title_box.addWidget(title)
        subtitle = QLabel(
            "Explore how people, commitments, conversations, and evidence connect."
        )
        subtitle.setObjectName("muted")
        subtitle.setWordWrap(True)
        title_box.addWidget(subtitle)
        header.addLayout(title_box, 1)
        layout.addLayout(header)
        layout.addLayout(self._build_stats())
        self.tabs = QTabWidget()
        self.graph_tab = self._build_graph_tab()
        self.records_tab = self._build_records_tab()
        self.timeline_tab = self._build_timeline_tab()
        self.tabs.addTab(self.graph_tab, "Graph")
        self.tabs.addTab(self.records_tab, "Records")
        self.tabs.addTab(self.timeline_tab, "Timeline")
        layout.addWidget(self.tabs, 1)

    def _build_stats(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(10)
        definitions = [
            ("people", "People"),
            ("active_commitments", "Active commitments"),
            ("waiting_for", "Waiting for"),
            ("blocked_commitments", "Blocked"),
            ("connected_memories", "Connected memories"),
        ]
        for key, caption in definitions:
            card = QFrame()
            card.setObjectName("metric_card")
            card.setMinimumHeight(68)
            card_layout = QVBoxLayout(card)
            card_layout.setContentsMargins(14, 8, 14, 8)
            card_layout.setSpacing(0)
            value = QLabel("0")
            value.setStyleSheet("font-size: 22px; font-weight: 800;")
            card_layout.addWidget(value)
            label = QLabel(caption)
            label.setObjectName("muted")
            card_layout.addWidget(label)
            self._stat_values[key] = value
            row.addWidget(card, 1)
        return row

    def _build_graph_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 8, 0, 0)
        layout.setSpacing(8)

        search_row = QHBoxLayout()
        self.semantic_check = QCheckBox("Semantic")
        semantic_available = (
            hasattr(self.container, "vectors") and hasattr(self.container, "embedder")
        )
        self.semantic_check.setChecked(semantic_available)
        self.semantic_check.setEnabled(semantic_available)
        self.semantic_check.setToolTip(
            "Also search related memories through local Qdrant embeddings. "
            "Semantic matches are suggestions and never create graph edges."
        )
        self.semantic_check.toggled.connect(self._semantic_toggled)
        search_row.addWidget(self.semantic_check)
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText(
            "Search people, commitments, emails, documents, or memory content…"
        )
        self.search_input.textChanged.connect(self._search_text_changed)
        self.search_input.returnPressed.connect(self._focus_first_search_result)
        search_row.addWidget(self.search_input, 1)
        layout.addLayout(search_row)
        self.search_results = QListWidget()
        self.search_results.setMaximumHeight(150)
        self.search_results.hide()
        self.search_results.itemClicked.connect(self._search_result_clicked)
        layout.addWidget(self.search_results)
        self.semantic_status = QLabel("")
        self.semantic_status.setObjectName("muted")
        self.semantic_status.hide()
        layout.addWidget(self.semantic_status)
        self._semantic_timer = QTimer(self)
        self._semantic_timer.setSingleShot(True)
        self._semantic_timer.setInterval(450)
        self._semantic_timer.timeout.connect(self._start_semantic_search)

        controls = QHBoxLayout()
        controls.setSpacing(6)
        layout_label = QLabel("Layout:")
        layout_label.setObjectName("muted")
        controls.addWidget(layout_label)
        self.layout_combo = QComboBox()
        self.layout_combo.addItem("Auto", "auto")
        self.layout_combo.addItem("Layered", "layered")
        self.layout_combo.addItem("Relationship", "relationship")
        self.layout_combo.currentIndexChanged.connect(self._layout_changed)
        controls.addWidget(self.layout_combo)
        for label, handler in (
            ("Fit", self.graph_canvas_fit),
            ("Reset", self.graph_canvas_reset),
            ("Expand", self.graph_expand),
            ("Collapse", self.graph_collapse),
            ("Incoming", lambda: self.graph_highlight("in")),
            ("Outgoing", lambda: self.graph_highlight("out")),
            ("Neighbours", lambda: self.graph_highlight("neighbours")),
            ("Clear highlight", self.graph_clear_highlight),
        ):
            button = QPushButton(label)
            button.setObjectName("secondary")
            button.clicked.connect(handler)
            controls.addWidget(button)
        controls.addStretch()
        layout.addLayout(controls)

        filters = QHBoxLayout()
        filters.setSpacing(8)
        filter_title = QLabel("Show:")
        filter_title.setObjectName("muted")
        filters.addWidget(filter_title)
        self.node_filter_checks: dict[GraphNodeKind, QCheckBox] = {}
        for kind, label in FILTER_NODE_KINDS:
            check = QCheckBox(label)
            check.setChecked(True)
            check.toggled.connect(lambda _checked: self._apply_filters())
            self.node_filter_checks[kind] = check
            filters.addWidget(check)
        filters.addSpacing(8)
        self.status_combo = QComboBox()
        for label, value in STATUS_OPTIONS:
            self.status_combo.addItem(label, value)
        self.status_combo.currentIndexChanged.connect(lambda _index: self._apply_filters())
        filters.addWidget(self.status_combo)
        self.relationship_combo = QComboBox()
        for label, value in RELATIONSHIP_OPTIONS:
            self.relationship_combo.addItem(label, value)
        self.relationship_combo.currentIndexChanged.connect(
            lambda _index: self._apply_filters()
        )
        filters.addWidget(self.relationship_combo)
        filters.addStretch()
        layout.addLayout(filters)

        self.graph_summary = QLabel("")
        self.graph_summary.setObjectName("muted")
        layout.addWidget(self.graph_summary)

        self.graph_stack = QStackedWidget()
        self.empty_state = self._build_empty_state()
        self.graph_canvas = GraphCanvas()
        self.graph_canvas.setMinimumWidth(520)
        self.graph_canvas.nodeSelected.connect(self._show_node_details)
        self.graph_canvas.edgeSelected.connect(self._show_edge_details)
        self.graph_canvas.selectionCleared.connect(self._show_graph_placeholder)
        self.graph_details = DetailPanel()
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(self.graph_canvas)
        splitter.addWidget(self.graph_details)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 0)
        splitter.setSizes([800, 340])
        self.graph_splitter = splitter
        self.graph_stack.addWidget(self.empty_state)
        self.graph_stack.addWidget(splitter)
        layout.addWidget(self.graph_stack, 1)
        page.setLayout(layout)
        return page

    def _build_empty_state(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.addStretch()
        card = QFrame()
        card.setObjectName("card")
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(36, 30, 36, 30)
        card_layout.setSpacing(10)
        icon = QLabel("✦")
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon.setStyleSheet(f"font-size: 34px; color: {COLOR_TERRACOTTA};")
        card_layout.addWidget(icon)
        title = QLabel("Your knowledge graph is waiting to grow.")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setStyleSheet("font-size: 18px; font-weight: 700;")
        card_layout.addWidget(title)
        body = QLabel(
            "Capture a commitment, add a contact through your email conversations, "
            "or record a memory. Pactlyn only draws edges from real stored records and "
            "validated relationships."
        )
        body.setWordWrap(True)
        body.setAlignment(Qt.AlignmentFlag.AlignCenter)
        body.setObjectName("muted")
        card_layout.addWidget(body)
        buttons = QHBoxLayout()
        create = QPushButton("Create a commitment")
        create.setObjectName("primary")
        create.clicked.connect(self.createCommitmentRequested.emit)
        assistant = QPushButton("Open Assistant")
        assistant.setObjectName("secondary")
        assistant.clicked.connect(
            lambda: self.navigateRequested.emit("assistant", "")
        )
        buttons.addStretch()
        buttons.addWidget(create)
        buttons.addWidget(assistant)
        buttons.addStretch()
        card_layout.addLayout(buttons)
        layout.addWidget(card)
        layout.addStretch()
        page.setLayout(layout)
        return page

    def _build_records_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 8, 0, 0)
        layout.setSpacing(8)
        search_row = QHBoxLayout()
        self.record_search = QLineEdit()
        self.record_search.setPlaceholderText("Search memory content, source, or related record…")
        self.record_search.textChanged.connect(self._apply_record_search)
        search_row.addWidget(self.record_search, 1)
        layout.addLayout(search_row)
        splitter = QSplitter(Qt.Orientation.Horizontal)
        self.records_list = QListWidget()
        self.records_list.itemSelectionChanged.connect(self._record_selection_changed)
        self.record_details = DetailPanel()
        splitter.addWidget(self.records_list)
        splitter.addWidget(self.record_details)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 0)
        splitter.setSizes([760, 340])
        layout.addWidget(splitter, 1)
        page.setLayout(layout)
        return page

    def _build_timeline_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 8, 0, 0)
        layout.setSpacing(8)
        row = QHBoxLayout()
        row.setSpacing(8)
        row.addWidget(QLabel("From:"))
        self.timeline_from = QDateEdit()
        self.timeline_from.setCalendarPopup(True)
        self.timeline_from.setDisplayFormat("dd MMM yyyy")
        self.timeline_from.dateChanged.connect(lambda _value: self._apply_timeline_filters())
        row.addWidget(self.timeline_from)
        row.addWidget(QLabel("To:"))
        self.timeline_to = QDateEdit()
        self.timeline_to.setCalendarPopup(True)
        self.timeline_to.setDisplayFormat("dd MMM yyyy")
        self.timeline_to.dateChanged.connect(lambda _value: self._apply_timeline_filters())
        row.addWidget(self.timeline_to)
        self.timeline_contact = QComboBox()
        self.timeline_contact.currentIndexChanged.connect(
            lambda _value: self._apply_timeline_filters()
        )
        row.addWidget(self.timeline_contact)
        self.timeline_commitment = QComboBox()
        self.timeline_commitment.currentIndexChanged.connect(
            lambda _value: self._apply_timeline_filters()
        )
        row.addWidget(self.timeline_commitment)
        self.timeline_source = QComboBox()
        self.timeline_source.currentIndexChanged.connect(
            lambda _value: self._apply_timeline_filters()
        )
        row.addWidget(self.timeline_source)
        clear = QPushButton("Clear filters")
        clear.setObjectName("secondary")
        clear.clicked.connect(self._clear_timeline_filters)
        row.addWidget(clear)
        row.addStretch()
        layout.addLayout(row)
        self.timeline_tree = QTreeWidget()
        self.timeline_tree.setHeaderLabels(["When", "Event", "Source"])
        header = self.timeline_tree.header()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.timeline_tree.itemDoubleClicked.connect(self._timeline_item_activated)
        layout.addWidget(self.timeline_tree, 1)
        page.setLayout(layout)
        return page

    def _layout_changed(self, _index: int) -> None:
        mode = self.layout_combo.currentData()
        if isinstance(mode, str):
            self.graph_canvas.set_layout_mode(mode)

    def _current_filter(self) -> GraphFilter:
        kinds = frozenset(
            kind
            for kind, check in self.node_filter_checks.items()
            if check.isChecked()
        )
        status = self.status_combo.currentData()
        group = self.relationship_combo.currentData()
        return GraphFilter(
            node_kinds=kinds,
            status=status if isinstance(status, str) else None,
            relationship_group=group if isinstance(group, str) else None,
        )

    def _apply_filters(self) -> None:
        if not hasattr(self, "graph_canvas"):
            return
        self.graph_canvas.set_filter(self._current_filter())
        total = len(self._graph.nodes)
        visible = self.graph_canvas.visible_node_count
        edges = self.graph_canvas.visible_edge_count
        if total == 0:
            self.graph_summary.setText("No canonical records yet.")
        else:
            suffix = " · large graph trimmed for performance" if self._graph.limited else ""
            self.graph_summary.setText(
                f"{visible} of {total} nodes visible · {edges} relationships shown{suffix}"
            )

    def refresh(self) -> None:
        session = self.container.session()
        try:
            graph = KnowledgeGraphRepository(session).build()
        finally:
            session.close()
        first_load = not self._has_loaded
        was_empty = self._graph.empty
        self._graph = graph
        self._has_loaded = True
        self._update_stats(graph)
        self._populate_search(graph)
        selected = self.graph_canvas.selected_node_id()
        self.graph_canvas.set_graph(
            graph,
            fit=first_load or was_empty or graph.empty,
        )
        if graph.nodes:
            self.graph_stack.setCurrentWidget(self.graph_splitter)
        else:
            self.graph_stack.setCurrentWidget(self.empty_state)
        self._apply_filters()
        self._populate_records(graph)
        self._populate_timeline(graph)
        if selected and graph.node(selected):
            self.graph_canvas.focus_node(selected, center=False)
            self._show_node_details(selected)
        else:
            self._show_graph_placeholder()
        record_id = self._selected_record_id()
        if record_id and record_id in self._records_by_id:
            self._show_record_details(record_id)
        else:
            self._show_record_placeholder()

    def set_theme(self, mode: ThemeMode) -> None:
        self._mode = mode
        self.graph_canvas.set_theme(mode)
        if self.graph_canvas.selected_node_id():
            selected = self.graph_canvas.selected_node_id()
            if selected:
                self._show_node_details(selected)

    def _update_stats(self, graph: KnowledgeGraph) -> None:
        stats = graph.stats
        values = {
            "people": stats.people,
            "active_commitments": stats.active_commitments,
            "waiting_for": stats.waiting_for,
            "blocked_commitments": stats.blocked_commitments,
            "connected_memories": stats.connected_memories,
        }
        for key, value in values.items():
            label = self._stat_values.get(key)
            if label is not None:
                label.setText(str(value))

    def _populate_search(self, graph: KnowledgeGraph) -> None:
        selected = self.search_input.text()
        self._semantic_hits = ()
        self._semantic_query = ""
        self._semantic_timer.stop()
        self.semantic_status.hide()
        self.search_input.blockSignals(True)
        self.search_input.setText(selected)
        self.search_input.blockSignals(False)
        self._update_search_results(selected)

    def _search_text_changed(self, text: str) -> None:
        self._semantic_hits = ()
        self._semantic_query = ""
        self._semantic_timer.stop()
        if self.semantic_check.isChecked() and text.strip():
            self.semantic_status.setText("Searching related memories…")
            self.semantic_status.show()
            self._semantic_timer.start()
        else:
            self.semantic_status.hide()
            self.semantic_status.clear()
        self._update_search_results(text)

    def _semantic_toggled(self, checked: bool) -> None:
        if checked and self.search_input.text().strip():
            self.semantic_status.setText("Searching related memories…")
            self.semantic_status.show()
            self._semantic_timer.start()
        else:
            self._semantic_timer.stop()
            self._semantic_hits = ()
            self._semantic_query = ""
            self.semantic_status.hide()
            self._update_search_results(self.search_input.text())

    def _start_semantic_search(self) -> None:
        query = self.search_input.text().strip()
        if not query or not self.semantic_check.isChecked():
            return
        if not (
            hasattr(self.container, "vectors") and hasattr(self.container, "embedder")
        ):
            return
        if self._semantic_worker is not None and self._semantic_worker.isRunning():
            self._semantic_timer.start()
            return
        worker = SemanticSearchWorker(self.container, query, self)
        worker.resultsReady.connect(self._semantic_results)
        worker.searchFailed.connect(self._semantic_failed)
        worker.finished.connect(self._semantic_finished)
        self._semantic_worker = worker
        self.semantic_status.setText("Searching related memories…")
        self.semantic_status.show()
        worker.start()

    def _semantic_finished(self) -> None:
        worker = self.sender()
        if isinstance(worker, SemanticSearchWorker):
            if self._semantic_worker is worker:
                self._semantic_worker = None
            worker.deleteLater()

    def _semantic_results(self, query: str, hits: object) -> None:
        if query != self.search_input.text().strip():
            return
        values = tuple(hits) if isinstance(hits, tuple) else ()
        self._semantic_hits = tuple(
            hit for hit in values if isinstance(hit, SemanticMemoryHit)
        )
        self._semantic_query = query
        if self._semantic_hits:
            count = len(self._semantic_hits)
            self.semantic_status.setText(
                f"{count} related memor{'y' if count == 1 else 'ies'} found in the local index."
            )
        else:
            self.semantic_status.setText("No related memories found in the local index.")
        self.semantic_status.show()
        self._update_search_results(query)

    def _semantic_failed(self, query: str, _message: str) -> None:
        if query != self.search_input.text().strip():
            return
        self._semantic_hits = ()
        self._semantic_query = query
        self.semantic_status.setText(
            "Semantic search is unavailable. Local Ollama embeddings may not be running."
        )
        self.semantic_status.show()
        self._update_search_results(query)

    def _update_search_results(self, text: str) -> None:
        query = text.strip()
        self.search_results.clear()
        if not query:
            self.search_results.hide()
            return
        results = self._graph.search(query)[:12]
        for node in results:
            item = QListWidgetItem(f"{node.label} · {NODE_TITLES[node.kind]}")
            item.setData(Qt.ItemDataRole.UserRole, node.id)
            item.setToolTip(node.subtitle)
            self.search_results.addItem(item)
        if (
            self._semantic_hits
            and self._semantic_query == query
            and self.semantic_check.isChecked()
        ):
            if self.search_results.count():
                separator = QListWidgetItem("Related memories · local semantic index")
                separator.setFlags(Qt.ItemFlag.NoItemFlags)
                self.search_results.addItem(separator)
            for hit in self._semantic_hits:
                item = QListWidgetItem(
                    f"✦ {_truncate(hit.content, 72)} · {hit.source}"
                )
                item.setData(Qt.ItemDataRole.UserRole, hit.node_id)
                item.setToolTip(
                    f"{hit.content}\n"
                    f"Related record: {hit.related_label}\n"
                    f"Similarity: {hit.score:.0%}"
                )
                self.search_results.addItem(item)
        if self.search_results.count() == 0 and not self.semantic_status.isVisible():
            item = QListWidgetItem("No matching nodes")
            item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEnabled)
            self.search_results.addItem(item)
        self.search_results.show()

    def _search_result_clicked(self, item: QListWidgetItem) -> None:
        node_id = item.data(Qt.ItemDataRole.UserRole)
        if isinstance(node_id, str):
            self._focus_node(node_id)

    def _focus_first_search_result(self) -> None:
        if self.search_results.count() == 0:
            self._update_search_results(self.search_input.text())
        for index in range(self.search_results.count()):
            item = self.search_results.item(index)
            node_id = item.data(Qt.ItemDataRole.UserRole)
            if isinstance(node_id, str):
                self._focus_node(node_id)
                return

    def _focus_node(self, node_id: str) -> None:
        node = self._graph.node(node_id)
        if node is None:
            return
        kinds = {kind for kind, check in self.node_filter_checks.items() if check.isChecked()}
        if node.kind not in kinds:
            check = self.node_filter_checks.get(node.kind)
            if check is not None:
                check.setChecked(True)
        if self.status_combo.currentData() and node.kind == GraphNodeKind.COMMITMENT:
            self.status_combo.setCurrentIndex(0)
        if self.relationship_combo.currentData():
            self.relationship_combo.setCurrentIndex(0)
        self.graph_canvas.focus_node(node_id)
        self.search_results.hide()
        self.tabs.setCurrentWidget(self.graph_tab)

    def _show_graph_placeholder(self) -> None:
        self.graph_details.show_content(
            "<p>Select a node or relationship to inspect its stored details and evidence.</p>",
            "No technical metadata selected.",
        )

    def _show_record_placeholder(self) -> None:
        self.record_details.show_content(
            "<p>Select a memory record to read its provenance.</p>",
            "No technical metadata selected.",
        )

    def _show_details_placeholder(self) -> None:
        self._show_graph_placeholder()
        if hasattr(self, "record_details"):
            self._show_record_placeholder()

    def _node_action(self, node: GraphNode) -> tuple[str, str, Callable[[], None]] | None:
        if node.kind == GraphNodeKind.COMMITMENT and node.entity_id:
            return (
                "Open in Commitments",
                node.entity_id,
                lambda: self.navigateRequested.emit("commitments", node.entity_id or ""),
            )
        if node.kind == GraphNodeKind.EMAIL and node.entity_id:
            return (
                "Open in Email Centre",
                node.entity_id,
                lambda: self.navigateRequested.emit("email", node.entity_id or ""),
            )
        if node.kind == GraphNodeKind.EVENT:
            for edge in self._graph.edges_for(node.id, direction="in"):
                if edge.kind == GraphEdgeKind.HAS_EVENT:
                    source = self._graph.node(edge.source_id)
                    if source and source.entity_id:
                        source_id = source.entity_id
                        return (
                            "Open commitment",
                            source_id,
                            lambda source_id=source_id: self.navigateRequested.emit(
                                "commitments", source_id
                            ),
                        )
        if node.kind == GraphNodeKind.DOCUMENT:
            for edge in self._graph.edges_for(node.id, direction="in"):
                if edge.kind == GraphEdgeKind.HAS_ATTACHMENT:
                    source = self._graph.node(edge.source_id)
                    if source and source.entity_id:
                        source_id = source.entity_id
                        return (
                            "Open email thread",
                            source_id,
                            lambda source_id=source_id: self.navigateRequested.emit(
                                "email", source_id
                            ),
                        )
        if node.kind == GraphNodeKind.MEMORY and node.entity_id:
            return (
                "Open memory record",
                node.entity_id,
                lambda: self._open_record(node.entity_id or ""),
            )
        return None

    def _show_node_details(self, node_id: str) -> None:
        node = self._graph.node(node_id)
        if node is None:
            self._show_details_placeholder()
            return
        parts = [
            f"<h2>{_safe(node.label)}</h2>",
            f"<p style='margin-top:0;'>{_safe(NODE_TITLES[node.kind])} · {_safe(node.subtitle)}</p>",
        ]
        for label, value in node.details:
            parts.append(f"<p><b>{_safe(label)}</b><br>{_safe(value)}</p>")
        outgoing = self._graph.edges_for(node_id, direction="out")
        incoming = self._graph.edges_for(node_id, direction="in")
        if outgoing or incoming:
            parts.append("<h3>Connections</h3><ul>")
            for edge in outgoing:
                target = self._graph.node(edge.target_id)
                parts.append(
                    f"<li>→ <b>{_safe(edge.label)}</b> {_safe(target.label if target else edge.target_id)}</li>"
                )
            for edge in incoming:
                source = self._graph.node(edge.source_id)
                parts.append(
                    f"<li>← <b>{_safe(edge.label)}</b> {_safe(source.label if source else edge.source_id)}</li>"
                )
            parts.append("</ul>")
        related_timeline = [
            item
            for item in self._graph.timeline
            if item.node_id == node.id
            or (node.kind == GraphNodeKind.PERSON and item.person_node_id == node.id)
        ]
        if related_timeline:
            parts.append("<h3>Recent activity</h3><ul>")
            for item in related_timeline[:6]:
                parts.append(
                    f"<li><b>{_safe(_format_date(item.timestamp))}</b> · {_safe(item.title)}</li>"
                )
            parts.append("</ul>")
        developer = "\n".join(
            f"{label}: {value}"
            for label, value in (*node.developer, ("Node ID", node.id), ("Entity ID", node.entity_id or ""))
            if value
        )
        action = self._node_action(node)
        if action is not None:
            label, _target, callback = action
            self.graph_details.show_content(
                "".join(parts),
                developer,
                action_label=label,
                action=callback,
            )
        else:
            self.graph_details.show_content("".join(parts), developer)

    def _show_edge_details(self, edge_id: str) -> None:
        edge = next((item for item in self._graph.edges if item.id == edge_id), None)
        if edge is None:
            self._show_details_placeholder()
            return
        source = self._graph.node(edge.source_id)
        target = self._graph.node(edge.target_id)
        parts = [
            f"<h2>{_safe(edge.label.title())}</h2>",
            f"<p style='margin-top:0;'>{_safe(edge.kind.value)}</p>",
            f"<p><b>From</b><br>{_safe(source.label if source else edge.source_id)}</p>",
            f"<p><b>To</b><br>{_safe(target.label if target else edge.target_id)}</p>",
        ]
        if edge.evidence:
            parts.append(f"<p><b>Supporting statement</b><br>{_safe(edge.evidence)}</p>")
        if edge.confidence is not None:
            parts.append(f"<p><b>Confidence</b><br>{edge.confidence:.0%}</p>")
        parts.append(
            f"<p><b>Review status</b><br>{_safe(_edge_review_label(edge))}</p>"
        )
        if edge.validation_status:
            parts.append(
                f"<p><b>Validation</b><br>{_safe(edge.validation_status.replace('_', ' ').title())}</p>"
            )
        if edge.origin:
            parts.append(f"<p><b>Origin</b><br>{_safe(edge.origin.replace('_', ' ').title())}</p>")
        developer = "\n".join(
            f"{label}: {value}"
            for label, value in (*edge.developer, ("Edge ID", edge.id))
            if value
        )
        self.graph_details.show_content("".join(parts), developer)

    def _populate_records(self, graph: KnowledgeGraph) -> None:
        selected = self._selected_record_id()
        self._records_by_id = {record.id: record for record in graph.records}
        self._apply_record_search()
        if selected and selected in self._records_by_id:
            self._select_record(selected)

    def _selected_record_id(self) -> str | None:
        item = self.records_list.currentItem() if hasattr(self, "records_list") else None
        if item is None:
            return None
        value = item.data(Qt.ItemDataRole.UserRole)
        return str(value) if value else None

    def _apply_record_search(self) -> None:
        query = self.record_search.text().strip().casefold()
        selected = self._selected_record_id()
        self.records_list.clear()
        records = sorted(
            self._records_by_id.values(),
            key=lambda record: record.created_at or datetime.min,
            reverse=True,
        )
        shown = 0
        for record in records:
            haystack = (
                f"{record.content} {record.kind} {record.source} "
                f"{record.related_label} {record.provenance}"
            ).casefold()
            if query and query not in haystack:
                continue
            shown += 1
            content = _truncate(record.content, 110) or "(empty memory)"
            metadata = (
                f"{record.kind.title()} · {record.source} · {_format_date(record.created_at)}"
                f" · {record.related_label}"
            )
            item = QListWidgetItem(f"{content}\n{metadata}")
            item.setData(Qt.ItemDataRole.UserRole, record.id)
            item.setToolTip(record.content)
            self.records_list.addItem(item)
        if shown == 0:
            item = QListWidgetItem(
                "No memory records match." if self._records_by_id else "No memory records yet."
            )
            item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEnabled)
            self.records_list.addItem(item)
        if selected:
            self._select_record(selected, emit=False)

    def _select_record(self, record_id: str, *, emit: bool = True) -> None:
        for index in range(self.records_list.count()):
            item = self.records_list.item(index)
            if item.data(Qt.ItemDataRole.UserRole) == record_id:
                self.records_list.setCurrentItem(item)
                if emit:
                    self._show_record_details(record_id)
                return

    def _record_selection_changed(self) -> None:
        record_id = self._selected_record_id()
        if record_id:
            self._show_record_details(record_id)

    def _show_record_details(self, record_id: str) -> None:
        record = self._records_by_id.get(record_id)
        if record is None:
            return

        # Personal-fact records get a distinct, user-friendly display.
        if record.source_type == "personal_fact":
            cat_label = record.source.replace("Personal profile · ", "").strip() or "Personal fact"
            confirmation = "Confirmed"
            for dev_key, dev_val in record.developer:
                if dev_key == "Confirmation state":
                    confirmation = dev_val.replace("_", " ").title()
                    break
            parts = [
                f"<h2>{_safe(record.content)}</h2>",
                f"<p style='margin-top:0;color:#666;'>{_safe(cat_label)} · {_safe(confirmation)}</p>",
                f"<p><b>Source</b><br>{_safe(record.provenance)}</p>",
                f"<p><b>Created</b><br>{_safe(_format_datetime(record.created_at))}</p>",
            ]
        else:
            parts = [
                "<h2>Memory record</h2>",
                f"<p>{_safe(record.content)}</p>",
                f"<p><b>Kind</b><br>{_safe(record.kind.title())}</p>",
                f"<p><b>Source</b><br>{_safe(record.source)}</p>",
                f"<p><b>Created</b><br>{_safe(_format_datetime(record.created_at))}</p>",
                f"<p><b>Related record</b><br>{_safe(record.related_label)}</p>",
                f"<p><b>Provenance</b><br>{_safe(record.provenance)}</p>",
            ]

        node = self._graph.node(record.related_node_id) if record.related_node_id else None
        action: Callable[[], None] | None = None
        action_label = ""
        if node is not None and node.kind == GraphNodeKind.COMMITMENT and node.entity_id:
            action_label = "Open in Commitments"
            action = partial(
                self.navigateRequested.emit, "commitments", node.entity_id
            )
        elif node is not None and node.kind == GraphNodeKind.EMAIL and node.entity_id:
            action_label = "Open in Email Centre"
            action = partial(self.navigateRequested.emit, "email", node.entity_id)
        self.record_details.show_content(
            "".join(parts),
            "\n".join(f"{label}: {value}" for label, value in record.developer if value),
            action_label=action_label,
            action=action,
        )

    def _open_record(self, record_id: str) -> None:
        self.tabs.setCurrentWidget(self.records_tab)
        self._select_record(record_id)

    def _populate_timeline(self, graph: KnowledgeGraph) -> None:
        self._timeline_items = graph.timeline
        self._populate_timeline_filters()
        self._apply_timeline_filters()

    def _timeline_combo_value(self, combo: QComboBox) -> str | None:
        value = combo.currentData()
        return value if isinstance(value, str) and value else None

    def _populate_timeline_filters(self) -> None:
        self.timeline_contact.blockSignals(True)
        self.timeline_commitment.blockSignals(True)
        self.timeline_source.blockSignals(True)
        contact_current = self._timeline_combo_value(self.timeline_contact)
        commitment_current = self._timeline_combo_value(self.timeline_commitment)
        source_current = self._timeline_combo_value(self.timeline_source)
        self.timeline_contact.clear()
        self.timeline_contact.addItem("All contacts", None)
        self.timeline_commitment.clear()
        self.timeline_commitment.addItem("All commitments", None)
        self.timeline_source.clear()
        self.timeline_source.addItem("All sources", None)
        people = sorted(
            (node for node in self._graph.nodes if node.kind == GraphNodeKind.PERSON),
            key=lambda node: node.label.casefold(),
        )
        for node in people:
            self.timeline_contact.addItem(node.label, node.id)
        commitments = sorted(
            (node for node in self._graph.nodes if node.kind == GraphNodeKind.COMMITMENT),
            key=lambda node: node.label.casefold(),
        )
        for node in commitments:
            self.timeline_commitment.addItem(node.label, node.entity_id)
        sources = sorted({item.source for item in self._timeline_items if item.source})
        for source in sources:
            self.timeline_source.addItem(source, source)
        for combo, value in (
            (self.timeline_contact, contact_current),
            (self.timeline_commitment, commitment_current),
            (self.timeline_source, source_current),
        ):
            if value:
                index = combo.findData(value)
                if index >= 0:
                    combo.setCurrentIndex(index)
        self.timeline_contact.blockSignals(False)
        self.timeline_commitment.blockSignals(False)
        self.timeline_source.blockSignals(False)

        timestamps = [item.timestamp for item in self._timeline_items if item.timestamp]
        minimum = min(timestamps).date() if timestamps else date.today().replace(year=date.today().year - 1)
        maximum = max(timestamps).date() if timestamps else date.today()
        following_full_range = (
            self._timeline_min is not None
            and self._timeline_max is not None
            and self.timeline_from.date() == QDate(self._timeline_min)
            and self.timeline_to.date() == QDate(self._timeline_max)
        )
        self.timeline_from.blockSignals(True)
        self.timeline_to.blockSignals(True)
        self.timeline_from.setDateRange(QDate(minimum), QDate(maximum))
        self.timeline_to.setDateRange(QDate(minimum), QDate(maximum))
        if not self._timeline_has_loaded or following_full_range:
            self.timeline_from.setDate(QDate(minimum))
            self.timeline_to.setDate(QDate(maximum))
            self._timeline_has_loaded = True
        else:
            if self.timeline_from.date() < QDate(minimum):
                self.timeline_from.setDate(QDate(minimum))
            if self.timeline_to.date() > QDate(maximum):
                self.timeline_to.setDate(QDate(maximum))
        self._timeline_min = minimum
        self._timeline_max = maximum
        self.timeline_from.blockSignals(False)
        self.timeline_to.blockSignals(False)

    def _apply_timeline_filters(self) -> None:
        if not hasattr(self, "timeline_tree"):
            return
        start = cast(date, self.timeline_from.date().toPython())
        end = cast(date, self.timeline_to.date().toPython())
        contact = self._timeline_combo_value(self.timeline_contact)
        commitment = self._timeline_combo_value(self.timeline_commitment)
        source = self._timeline_combo_value(self.timeline_source)

        # Audit-only timeline events are hidden from the user-facing view.
        # They remain in the underlying data for the developer pane.
        _AUDIT_TITLE_PREFIXES = ("Commitment captured ·", "Commitment updated ·")

        filtered: list[GraphTimelineItem] = []
        seen_event_ids: set[str] = set()
        for item in self._timeline_items:
            if item.timestamp is not None:
                item_date = item.timestamp.date()
                if item_date < start or item_date > end:
                    continue
            if contact and item.person_node_id != contact:
                continue
            if commitment and item.commitment_id != commitment:
                continue
            if source and item.source != source:
                continue
            # Suppress audit-only items (e.g. "Commitment captured · …")
            if any(item.title.startswith(prefix) for prefix in _AUDIT_TITLE_PREFIXES):
                continue
            # Deduplicate by stable identity key to prevent repeated ingestion noise.
            key = item.id
            if key in seen_event_ids:
                continue
            seen_event_ids.add(key)
            filtered.append(item)

        self.timeline_tree.clear()
        if not filtered:
            root = QTreeWidgetItem(["No events", "No timeline items match these filters.", ""])
            self.timeline_tree.addTopLevelItem(root)
            return
        groups: dict[str, list[GraphTimelineItem]] = {}
        for item in filtered:
            key = _format_date(item.timestamp)
            groups.setdefault(key, []).append(item)
        for day, items in groups.items():
            group = QTreeWidgetItem([day, f"{len(items)} item" + ("" if len(items) == 1 else "s"), ""])
            group.setFirstColumnSpanned(False)
            self.timeline_tree.addTopLevelItem(group)
            for item in items:
                child = QTreeWidgetItem(
                    [_format_time(item.timestamp), item.title, item.source]
                )
                child.setToolTip(1, item.detail)
                child.setData(0, Qt.ItemDataRole.UserRole, item.node_id)
                child.setData(1, Qt.ItemDataRole.UserRole, item.commitment_id)
                child.setData(2, Qt.ItemDataRole.UserRole, item.memory_id)
                group.addChild(child)
            group.setExpanded(True)

    def _clear_timeline_filters(self) -> None:
        self.timeline_contact.setCurrentIndex(0)
        self.timeline_commitment.setCurrentIndex(0)
        self.timeline_source.setCurrentIndex(0)
        if self._timeline_items:
            timestamps = [item.timestamp for item in self._timeline_items if item.timestamp]
            if timestamps:
                self.timeline_from.setDate(QDate(min(timestamps).date()))
                self.timeline_to.setDate(QDate(max(timestamps).date()))

    def _timeline_item_activated(self, item: QTreeWidgetItem, _column: int) -> None:
        memory_id = item.data(2, Qt.ItemDataRole.UserRole)
        if isinstance(memory_id, str) and memory_id:
            self._open_record(memory_id)
            return
        node_id = item.data(0, Qt.ItemDataRole.UserRole)
        if isinstance(node_id, str) and node_id:
            self._focus_node(node_id)

    def graph_canvas_fit(self) -> None:
        self.graph_canvas.fit_graph()

    def graph_canvas_reset(self) -> None:
        self.graph_canvas.reset_layout()

    def graph_expand(self) -> None:
        self.graph_canvas.expand_selected()

    def graph_collapse(self) -> None:
        self.graph_canvas.collapse_selected()

    def graph_highlight(self, mode: str) -> None:
        self.graph_canvas.highlight(mode)

    def graph_clear_highlight(self) -> None:
        self.graph_canvas.clear_highlight()

    def shutdown(self) -> None:
        self._semantic_timer.stop()
        worker = self._semantic_worker
        if worker is not None and worker.isRunning():
            worker.wait(10_000)
        self._semantic_worker = None
