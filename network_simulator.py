import sys
import json
from enum import Enum
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Tuple
from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
                             QPushButton, QLabel, QSpinBox, QComboBox, QMessageBox, QGraphicsView,
                             QGraphicsScene, QGraphicsItem, QGraphicsEllipseItem, QGraphicsRectItem,
                             QGraphicsLineItem, QGraphicsTextItem, QGraphicsPathItem, QGraphicsPolygonItem,
                             QTabWidget, QTableWidget, QTableWidgetItem, QHeaderView, QSplitter, QDialog, QDockWidget)
from PyQt6.QtCore import Qt, QPointF, QRectF, QTimer, pyqtSignal, QObject, QLineF, QEvent
from PyQt6.QtGui import QColor, QPen, QBrush, QFont, QPainter, QPalette, QPolygonF, QDrag, QPixmap
from PyQt6.QtCore import Qt as QtCore
import math
import random
from aftm_model import reliability_R
from load_redistribution import proportional_redistribute_sources_full
import matplotlib.pyplot as plt


# ==================== ENUMS & DATA CLASSES ====================
class ComponentType(Enum):
    """Enum for different network component types."""
    SERVER = "Server"
    SWITCH = "Switch"
    SAN = "Storage Area Network"


class LoadBalancingStrategy(Enum):
    """Load balancing strategies."""
    ROUND_ROBIN = "Round Robin"
    LEAST_CONNECTIONS = "Least Connections"
    WEIGHTED_ROUND_ROBIN = "Weighted Round Robin"
    IP_HASH = "IP Hash"


class LoadDistributionStrategy(Enum):
    """Load distribution strategies for threshold-based redistribution."""
    NONE = "None"
    STATIC_THRESHOLD_RELIABILITY_SENSITIVE = "Static Threshold (Reliability-Sensitive)"
    STATIC_THRESHOLD_LOAD_SENSITIVE = "Static Threshold (Load-Sensitive)"
    DYNAMIC_THRESHOLD_RELIABILITY_SENSITIVE = "Dynamic Threshold (Reliability-Sensitive)"
    DYNAMIC_THRESHOLD_LOAD_SENSITIVE = "Dynamic Threshold (Load-Sensitive)"


@dataclass
class TrafficData:
    """Represents traffic flow between components."""
    source_id: str
    destination_id: str
    packets: int = 100
    bandwidth_used: float = 0.0
    latency_ms: float = 0.0
    packet_loss: float = 0.0  # Percentage
    

@dataclass
class ConnectionStats:
    """Statistics for a connection."""
    total_packets: int = 0
    packets_lost: int = 0
    total_latency: float = 0.0
    average_latency: float = 0.0
    bandwidth_usage: float = 0.0


# ==================== DIALOGS ====================
class RedistributionDialog(QDialog):
    """Dialog showing load redistribution results before and after."""
    
    def __init__(self, parent=None, before_loads=None, after_loads=None, threshold=50):
        super().__init__(parent)
        self.setWindowTitle("Load Redistribution Results")
        self.setGeometry(100, 100, 600, 400)
        
        layout = QVBoxLayout()
        
        # Title
        title = QLabel(f"Load redistribution triggered (threshold: {threshold})")
        title.setFont(QFont("Arial", 12, QFont.Weight.Bold))
        layout.addWidget(title)
        
        # Before/After table
        table = QTableWidget()
        table.setColumnCount(3)
        table.setHorizontalHeaderLabels(["Switch", "Before Load", "After Load"])
        table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        
        if before_loads and after_loads:
            switches = sorted(set(list(before_loads.keys()) + list(after_loads.keys())))
            table.setRowCount(len(switches))
            
            for i, switch_id in enumerate(switches):
                before = before_loads.get(switch_id, 0.0)
                after = after_loads.get(switch_id, 0.0)
                
                table.setItem(i, 0, QTableWidgetItem(switch_id))
                table.setItem(i, 1, QTableWidgetItem(f"{before:.2f}"))
                table.setItem(i, 2, QTableWidgetItem(f"{after:.2f}"))
        
        layout.addWidget(table)
        
        # Info label
        info = QLabel("All switches are now below threshold. Click 'Continue' to resume simulation.")
        layout.addWidget(info)
        
        # Button
        continue_btn = QPushButton("Continue")
        continue_btn.clicked.connect(self.accept)
        layout.addWidget(continue_btn)
        
        self.setLayout(layout)


# ==================== NETWORK COMPONENTS ====================
class NetworkComponent:
    """Base class for network components."""
    
    _id_counter = {}
    
    def __init__(self, component_type: ComponentType, x: float = 0, y: float = 0):
        # Generate unique ID
        if component_type not in NetworkComponent._id_counter:
            NetworkComponent._id_counter[component_type] = 0
        NetworkComponent._id_counter[component_type] += 1
        
        self.id = f"{component_type.value.replace(' ', '_')}_{NetworkComponent._id_counter[component_type]}"
        self.type = component_type
        self.x = x
        self.y = y
        self.width = 80
        self.height = 60
        self.connections: List[str] = []
        self.bandwidth_capacity = 1000  # Mbps
        self.current_load = 0  # Mbps
        # incoming requests per second (default 1 for switches, 0 for others)
        self.incoming_requests = 1 if component_type == ComponentType.SWITCH else 0
        # cumulative request load (accumulates each second during simulation)
        self.cumulative_request_load = 0.0
        # AFTM reliability parameters
        self.reliability = 1.0  # Current reliability (0-1)
        self.operational_time = 0.0  # Time in operation (seconds)
        self.base_lambda = 3e-6  # Base failure rate
        self.alpha = 1.0  # Load exponent
        self.active = True
        self.over_threshold = False  # Flag for switches that stay over threshold
        self.cpu_usage = 0.0  # For servers
        self.memory_usage = 0.0  # For servers
        self.storage_available = 1000  # GB for SAN
        self.storage_used = 0.0  # GB
        self.connection_stats: Dict[str, ConnectionStats] = {}
    
    def connect_to(self, target_id: str):
        """Create connection to another component."""
        if target_id not in self.connections:
            self.connections.append(target_id)
    
    def disconnect_from(self, target_id: str):
        """Remove connection to another component."""
        if target_id in self.connections:
            self.connections.remove(target_id)
    
    def get_load_percentage(self) -> float:
        """Get current load as percentage of capacity."""
        return (self.current_load / self.bandwidth_capacity) * 100 if self.bandwidth_capacity > 0 else 0
    
    def simulate_traffic(self, traffic: TrafficData):
        """Process incoming traffic."""
        if not self.active:
            traffic.packet_loss = 100
            return
        
        # Add latency based on load
        load_percentage = self.get_load_percentage()
        traffic.latency_ms += (1 + load_percentage / 100) * random.uniform(0.5, 2.0)
        
        # Calculate packet loss based on load
        if load_percentage > 90:
            traffic.packet_loss = 5 + (load_percentage - 90) * 0.5
        
        # Update connection stats
        if traffic.source_id not in self.connection_stats:
            self.connection_stats[traffic.source_id] = ConnectionStats()
        
        stats = self.connection_stats[traffic.source_id]
        stats.total_packets += traffic.packets
        stats.packets_lost += int(traffic.packets * traffic.packet_loss / 100)
        stats.total_latency += traffic.latency_ms
        stats.average_latency = stats.total_latency / max(1, stats.total_packets)
        stats.bandwidth_usage = self.current_load
    
    def to_dict(self) -> Dict:
        """Convert component to dictionary for serialization."""
        return {
            'id': self.id,
            'type': self.type.value,
            'x': self.x,
            'y': self.y,
            'connections': self.connections,
            'bandwidth_capacity': self.bandwidth_capacity,
            'cpu_usage': self.cpu_usage,
            'memory_usage': self.memory_usage,
            'storage_available': self.storage_available,
            'incoming_requests': self.incoming_requests,
            'cumulative_request_load': self.cumulative_request_load,
            'operational_time': self.operational_time,
            'base_lambda': self.base_lambda,
            'alpha': self.alpha,
        }


class LoadBalancer:
    """Handles load balancing across components."""
    
    def __init__(self, strategy: LoadBalancingStrategy = LoadBalancingStrategy.ROUND_ROBIN):
        self.strategy = strategy
        self.round_robin_index = 0
        self.weights: Dict[str, float] = {}
    
    def select_destination(self, available_destinations: List[Tuple[str, float]]) -> str:
        """Select destination based on load balancing strategy."""
        if not available_destinations:
            return None
        
        if self.strategy == LoadBalancingStrategy.ROUND_ROBIN:
            dest = available_destinations[self.round_robin_index % len(available_destinations)][0]
            self.round_robin_index += 1
            return dest
        
        elif self.strategy == LoadBalancingStrategy.LEAST_CONNECTIONS:
            return min(available_destinations, key=lambda x: x[1])[0]
        
        elif self.strategy == LoadBalancingStrategy.WEIGHTED_ROUND_ROBIN:
            total_weight = sum(w for _, w in available_destinations)
            choice = random.uniform(0, total_weight)
            current = 0
            for dest_id, weight in available_destinations:
                current += weight
                if choice <= current:
                    return dest_id
            return available_destinations[-1][0]
        
        elif self.strategy == LoadBalancingStrategy.IP_HASH:
            # Simulate IP hash by using a consistent random selection
            return available_destinations[hash(str(available_destinations)) % len(available_destinations)][0]
        
        return available_destinations[0][0]
    
    def set_weight(self, component_id: str, weight: float):
        """Set weight for weighted load balancing."""
        self.weights[component_id] = weight


# ==================== GRAPHICS COMPONENTS ====================
class GraphicsNetworkComponent(QGraphicsItem):
    """Graphics representation of a network component."""
    
    def __init__(self, component: NetworkComponent):
        super().__init__()
        self.component = component
        self.setPos(component.x, component.y)
        self.setAcceptHoverEvents(True)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable, True)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, True)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges, True)
        self.is_hovering = False
        self.setZValue(1)
    
    def boundingRect(self) -> QRectF:
        return QRectF(-40, -30, 80, 60)
    
    def paint(self, painter: QPainter, option, widget):
        # Draw based on component type
        rect = self.boundingRect()
        
        # Determine color based on type and load
        if self.component.type == ComponentType.SERVER:
            base_color = QColor(52, 152, 219)  # Blue
        elif self.component.type == ComponentType.SWITCH:
            base_color = QColor(46, 204, 113)  # Green
        else:  # SAN
            base_color = QColor(155, 89, 182)  # Purple
        
        # Adjust color based on load or over_threshold status
        if self.component.over_threshold:
            base_color = QColor(192, 57, 43)  # Dark red for persistent over-threshold
        else:
            load_percentage = self.component.get_load_percentage()
            if load_percentage > 80:
                base_color = QColor(231, 76, 60)  # Red for high load
            elif load_percentage > 50:
                base_color = QColor(241, 196, 15)  # Yellow for medium load
        
        # Draw main shape
        painter.setBrush(QBrush(base_color))
        painter.setPen(QPen(QColor(0, 0, 0), 2))
        
        if self.component.type == ComponentType.SERVER:
            painter.drawRect(rect)
        elif self.component.type == ComponentType.SWITCH:
            painter.drawEllipse(rect)
        else:  # SAN
            painter.drawRoundedRect(rect, 5, 5)
        
        # Draw selection indicator
        if self.isSelected():
            painter.setPen(QPen(QColor(255, 0, 0), 3, Qt.PenStyle.DashLine))
            painter.drawRect(rect)
        
        # Draw component ID
        painter.setPen(QPen(QColor(255, 255, 255), 1))
        font = QFont("Arial", 8, QFont.Weight.Bold)
        painter.setFont(font)
        painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, self.component.id.split('_')[0])
    
    def itemChange(self, change, value):
        if change == QGraphicsItem.GraphicsItemChange.ItemPositionChange:
            self.component.x = value.x()
            self.component.y = value.y()
        return super().itemChange(change, value)
    
    def hoverEnterEvent(self, event):
        self.is_hovering = True
        self.update()
    
    def hoverLeaveEvent(self, event):
        self.is_hovering = False
        self.update()


class GraphicsConnection(QGraphicsLineItem):
    """Graphics representation of a connection between components."""
    
    def __init__(self, source_item: GraphicsNetworkComponent, dest_item: GraphicsNetworkComponent):
        super().__init__()
        self.source_item = source_item
        self.dest_item = dest_item
        self.traffic_flow = 0.0
        self.update_line()
        self.setPen(QPen(QColor(100, 100, 100), 2))
        self.setZValue(0)
    
    def update_line(self):
        """Update line position based on item positions."""
        line = QLineF(self.source_item.scenePos(), self.dest_item.scenePos())
        self.setLine(line)
    
    def paint(self, painter: QPainter, option, widget):
        # Draw connection line with color based on traffic
        if self.traffic_flow > 0:
            # Green to red based on traffic
            intensity = min(self.traffic_flow / 500, 1.0)
            color = QColor(
                int(255 * intensity),
                int(200 * (1 - intensity)),
                int(50 * (1 - intensity))
            )
            painter.setPen(QPen(color, 2 + intensity * 2))
        else:
            painter.setPen(QPen(QColor(100, 100, 100), 2))
        
        painter.drawLine(self.line())
        
        # Draw arrow
        angle = math.atan2(self.line().dy(), self.line().dx())
        arrow_size = 10
        
        arrow_p1 = self.line().p2() - QPointF(arrow_size * math.cos(angle - math.pi / 6),
                                               arrow_size * math.sin(angle - math.pi / 6))
        arrow_p2 = self.line().p2() - QPointF(arrow_size * math.cos(angle + math.pi / 6),
                                               arrow_size * math.sin(angle + math.pi / 6))
        
        painter.setBrush(QBrush(painter.pen().color()))
        polygon = QPolygonF([self.line().p2(), arrow_p1, arrow_p2])
        painter.drawPolygon(polygon)


# ==================== MAIN APPLICATION ====================
class NetworkSimulator(QMainWindow):
    """Main application window for network simulation."""
    
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Network Simulator - SAN Environment")
        self.setGeometry(100, 100, 1400, 900)
        
        # Application state
        self.components: Dict[str, NetworkComponent] = {}
        self.graphics_items: Dict[str, GraphicsNetworkComponent] = {}
        self.connections_graphics: List[GraphicsConnection] = []
        self.load_balancer = LoadBalancer(LoadBalancingStrategy.ROUND_ROBIN)
        self.simulation_running = False
        self.simulation_paused = False
        self.simulation_time = 0
        self.selected_source = None
        self.selected_dest = None
        self.request_increment_rate = 0.1  # Increment per second (0.1 load increase per second per connected server)
        
        # Load distribution strategy
        self.load_distribution_strategy = LoadDistributionStrategy.NONE
        self.load_threshold = 50.0
        self.top_k = 1  # Number of switches to select for redistribution
        
        # Logging for graph generation
        self.load_history = {}  # {switch_id: [(timestamp, load), ...]}
        self.redistribution_log = []  # [(timestamp, event_description), ...]
        self.log_counter = 0  # Counter to log every 5 seconds (10 ticks of 500ms)
        
        # Dynamic threshold settings
        self.dynamic_threshold_reduction = 5.0  # Amount to reduce threshold after each successful redistribution
        self.dynamic_threshold_minimum = 20.0  # Minimum threshold (don't go below this)
        self.initial_load_threshold = 50.0  # Store initial threshold for reset
        
        # Create UI
        self.setup_ui()
        
        # Simulation timer
        self.sim_timer = QTimer()
        self.sim_timer.timeout.connect(self.run_simulation_step)
        
    def setup_ui(self):
        """Setup the user interface."""
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QHBoxLayout(central_widget)
        
        # Left panel - Canvas
        canvas_layout = QVBoxLayout()
        
        # Graphics view for network playground
        self.scene = QGraphicsScene()
        self.scene.setSceneRect(0, 0, 1000, 700)
        self.scene.setBackgroundBrush(QBrush(QColor(240, 240, 240)))
        
        self.view = QGraphicsView(self.scene)
        self.view.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.view.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        
        canvas_layout.addWidget(self.view)
        
        # Right panel - Controls
        control_layout = QVBoxLayout()
        
        # Component creation buttons
        control_layout.addWidget(QLabel("<b>Add Components</b>"))
        
        btn_server = QPushButton("Add Server")
        btn_server.clicked.connect(lambda: self.add_component(ComponentType.SERVER))
        control_layout.addWidget(btn_server)
        
        btn_switch = QPushButton("Add Switch")
        btn_switch.clicked.connect(lambda: self.add_component(ComponentType.SWITCH))
        control_layout.addWidget(btn_switch)
        
        btn_san = QPushButton("Add SAN")
        btn_san.clicked.connect(lambda: self.add_component(ComponentType.SAN))
        control_layout.addWidget(btn_san)
        
        control_layout.addWidget(QLabel("<b>Connection</b>"))
        
        btn_connect = QPushButton("Connect Selected (S1 → S2)")
        btn_connect.clicked.connect(self.create_connection)
        control_layout.addWidget(btn_connect)
        
        btn_disconnect = QPushButton("Disconnect Selected")
        btn_disconnect.clicked.connect(self.remove_connection)
        control_layout.addWidget(btn_disconnect)
        
        control_layout.addWidget(QLabel("<b>Load Balancing</b>"))
        
        self.lb_strategy = QComboBox()
        self.lb_strategy.addItems([s.value for s in LoadBalancingStrategy])
        self.lb_strategy.currentTextChanged.connect(self.update_load_balancing_strategy)
        control_layout.addWidget(QLabel("Strategy:"))
        control_layout.addWidget(self.lb_strategy)
        
        control_layout.addWidget(QLabel("<b>Load Distribution</b>"))
        
        self.load_dist_strategy = QComboBox()
        self.load_dist_strategy.addItems([s.value for s in LoadDistributionStrategy])
        self.load_dist_strategy.currentIndexChanged.connect(self.update_load_distribution_strategy)
        control_layout.addWidget(QLabel("Strategy:"))
        control_layout.addWidget(self.load_dist_strategy)
        
        self.threshold_spinbox = QSpinBox()
        self.threshold_spinbox.setMinimum(1)
        self.threshold_spinbox.setMaximum(1000)
        self.threshold_spinbox.setValue(50)
        self.threshold_spinbox.valueChanged.connect(self.update_load_threshold)
        control_layout.addWidget(QLabel("Threshold:"))
        control_layout.addWidget(self.threshold_spinbox)
        
        self.reduction_spinbox = QSpinBox()
        self.reduction_spinbox.setMinimum(1)
        self.reduction_spinbox.setMaximum(100)
        self.reduction_spinbox.setValue(5)
        self.reduction_spinbox.valueChanged.connect(self.update_threshold_reduction)
        control_layout.addWidget(QLabel("Reduction Factor:"))
        control_layout.addWidget(self.reduction_spinbox)
        
        self.top_k_spinbox = QSpinBox()
        self.top_k_spinbox.setMinimum(1)
        self.top_k_spinbox.setMaximum(100)
        self.top_k_spinbox.setValue(1)
        self.top_k_spinbox.valueChanged.connect(self.update_top_k)
        control_layout.addWidget(QLabel("Top K Switches:"))
        control_layout.addWidget(self.top_k_spinbox)
        
        control_layout.addWidget(QLabel("<b>Simulation</b>"))
        
        btn_start = QPushButton("Start Simulation")
        btn_start.clicked.connect(self.start_simulation)
        control_layout.addWidget(btn_start)
        
        btn_pause = QPushButton("Pause Simulation")
        btn_pause.clicked.connect(self.toggle_pause_simulation)
        control_layout.addWidget(btn_pause)
        
        btn_stop = QPushButton("Stop Simulation")
        btn_stop.clicked.connect(self.stop_simulation)
        control_layout.addWidget(btn_stop)
        
        btn_clear = QPushButton("Clear All")
        btn_clear.clicked.connect(self.clear_all)
        control_layout.addWidget(btn_clear)
        
        # Statistics tab - Switches only
        # Stats table will be added as dock widget
        self.stats_table = QTableWidget()
        self.stats_table.setColumnCount(7)
        self.stats_table.setHorizontalHeaderLabels(["Switch", "Load", "Req/s", "Reliability", "Lambda", "Alpha", "Op.Time"])
        header = self.stats_table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.stats_table.cellChanged.connect(self.on_stats_cell_changed)
        
        # Graph button
        btn_graph = QPushButton("Generate Graph")
        btn_graph.clicked.connect(self.generate_graph)
        control_layout.addWidget(btn_graph)
        
        # Save/Load
        control_layout.addWidget(QLabel("<b>Project</b>"))
        btn_save = QPushButton("Save Configuration")
        btn_save.clicked.connect(self.save_configuration)
        control_layout.addWidget(btn_save)
        
        btn_load = QPushButton("Load Configuration")
        btn_load.clicked.connect(self.load_configuration)
        control_layout.addWidget(btn_load)
        
        # Create right panel widget
        right_panel = QWidget()
        right_panel.setLayout(control_layout)
        right_panel.setMaximumWidth(300)
        
        # Add to main layout
        main_layout.addLayout(canvas_layout, 1)
        main_layout.addWidget(right_panel, 0)
        
        # Create dock widget for statistics table
        dock_widget = QDockWidget("Switches Statistics", self)
        dock_widget.setWidget(self.stats_table)
        self.addDockWidget(Qt.DockWidgetArea.TopDockWidgetArea, dock_widget)
        dock_widget.setFloating(False)
        dock_widget.setGeometry(0, 0, 400, 300)
    
    def add_component(self, component_type: ComponentType):
        """Add a new component to the network."""
        # Random position
        x = random.uniform(100, 800)
        y = random.uniform(100, 600)
        
        component = NetworkComponent(component_type, x, y)
        self.components[component.id] = component
        
        # Add graphics item
        graphics_item = GraphicsNetworkComponent(component)
        self.graphics_items[component.id] = graphics_item
        self.scene.addItem(graphics_item)
        
        # If this is a switch and simulation is running, initialize load_history for it
        if component_type == ComponentType.SWITCH and self.simulation_running:
            if component.id not in self.load_history:
                self.load_history[component.id] = []
                # Add initial data point with current time
                self.load_history[component.id].append((self.simulation_time, component.current_load))
        
        # Recalculate switch loads and update stats
        # If simulation is running, preserve cumulative request load
        if self.simulation_running:
            self.calculate_switch_loads(include_requests=True)
        else:
            self.calculate_switch_loads(include_requests=False)
        self.update_statistics()
        
        QMessageBox.information(self, "Success", f"Added {component_type.value} at ({x:.0f}, {y:.0f})")
    
    def create_connection(self):
        """Create connection between selected items."""
        selected_items = [item for item in self.scene.selectedItems() if isinstance(item, GraphicsNetworkComponent)]
        
        if len(selected_items) != 2:
            QMessageBox.warning(self, "Error", "Please select exactly 2 components to connect")
            return
        
        source = selected_items[0].component
        dest = selected_items[1].component
        
        source.connect_to(dest.id)
        dest.connect_to(source.id)
        
        # Create graphics connection
        conn = GraphicsConnection(selected_items[0], selected_items[1])
        self.connections_graphics.append(conn)
        self.scene.addItem(conn)
        
        # Recalculate switch loads after connection change
        # If simulation is running, preserve cumulative request load
        if self.simulation_running:
            self.calculate_switch_loads(include_requests=True)
        else:
            self.calculate_switch_loads(include_requests=False)
        self.update_statistics()
        
        # If either connected component is a switch that was over_threshold, trigger redistribution
        if self.simulation_running and (self.load_distribution_strategy == LoadDistributionStrategy.STATIC_THRESHOLD_RELIABILITY_SENSITIVE or \
                                       self.load_distribution_strategy == LoadDistributionStrategy.DYNAMIC_THRESHOLD_RELIABILITY_SENSITIVE):
            if (source.type == ComponentType.SWITCH and source.over_threshold) or \
               (dest.type == ComponentType.SWITCH and dest.over_threshold):
                print("[Info] New connection to over-threshold switch, triggering redistribution...")
                
                # Trigger the appropriate redistribution method
                if self.load_distribution_strategy == LoadDistributionStrategy.STATIC_THRESHOLD_RELIABILITY_SENSITIVE:
                    self.apply_static_threshold_redistribution()
                else:
                    self.apply_dynamic_threshold_redistribution()
        
        QMessageBox.information(self, "Connected", f"{source.id} → {dest.id}")
    
    def remove_connection(self):
        """Remove connection between selected items."""
        selected_items = [item for item in self.scene.selectedItems() if isinstance(item, GraphicsNetworkComponent)]
        
        if len(selected_items) != 2:
            QMessageBox.warning(self, "Error", "Please select exactly 2 components")
            return
        
        source = selected_items[0].component
        dest = selected_items[1].component
        
        source.disconnect_from(dest.id)
        dest.disconnect_from(source.id)
        
        # Remove graphics connection
        self.connections_graphics = [c for c in self.connections_graphics 
                                     if not ((c.source_item.component == source and c.dest_item.component == dest) or
                                            (c.source_item.component == dest and c.dest_item.component == source))]
        
        # Recalculate switch loads after connection change
        # If simulation is running, preserve cumulative request load
        if self.simulation_running:
            self.calculate_switch_loads(include_requests=True)
        else:
            self.calculate_switch_loads(include_requests=False)
        self.update_statistics()
        
        self.scene.update()
    
    def update_load_balancing_strategy(self, strategy_name: str):
        """Update load balancing strategy."""
        for strategy in LoadBalancingStrategy:
            if strategy.value == strategy_name:
                self.load_balancer.strategy = strategy
                break
    
    def update_load_distribution_strategy(self, index: int):
        """Update load distribution strategy."""
        strategies = list(LoadDistributionStrategy)
        if 0 <= index < len(strategies):
            self.load_distribution_strategy = strategies[index]
    
    def update_load_threshold(self, value: int):
        """Update load threshold for redistribution."""
        print(f"[DEBUG] update_load_threshold called: {value}")
        self.load_threshold = float(value)
        self.initial_load_threshold = float(value)  # Update initial threshold for dynamic strategy
    
    def update_threshold_reduction(self, value: int):
        """Update threshold reduction factor for dynamic strategy."""
        self.dynamic_threshold_reduction = float(value)
        print(f"[DEBUG] Threshold reduction factor updated to: {value}")
    
    def update_top_k(self, value: int):
        """Update top K switches for redistribution selection."""
        self.top_k = value
        print(f"[DEBUG] Top K switches updated to: {value}")
    
    def calculate_switch_loads(self, include_requests=False):
        """Calculate load for all switches based on connections and incoming requests.
        
        Args:
            include_requests: If True, include cumulative request load. If False, show base load only.
        
        Rules:
        - Base load (static): 20 × (connected servers) + 5 × (connected switches) + 10 × (connected SANs)
        - Dynamic load (per second, only if include_requests=True): += cumulative_request_load
        """
        for component in self.components.values():
            if component.type == ComponentType.SWITCH:
                base_load = 0
                
                # Calculate base load from connected components
                for neighbor_id in component.connections:
                    neighbor = self.components.get(neighbor_id)
                    if neighbor:
                        if neighbor.type == ComponentType.SERVER:
                            base_load += 20
                        elif neighbor.type == ComponentType.SWITCH:
                            base_load += 5
                        elif neighbor.type == ComponentType.SAN:
                            base_load += 10
                
                # Add cumulative request load only during simulation
                if include_requests:
                    component.current_load = max(0, base_load + component.cumulative_request_load)
                else:
                    component.current_load = max(0, base_load)
                
                # Update reliability based on current load and operational time
                component.reliability = reliability_R(
                    component.operational_time,
                    component.current_load,
                    component.base_lambda,
                    component.alpha
                )
    
    def start_simulation(self):
        """Start network simulation."""
        if not self.components:
            QMessageBox.warning(self, "Error", "Add components first")
            return
        
        # If already running, just unpause (don't reset)
        if self.simulation_running:
            self.simulation_paused = False
            return
        
        self.simulation_running = True
        self.simulation_paused = False
        self.simulation_time = 0
        
        # Disable threshold and reduction spinboxes during simulation
        self.threshold_spinbox.setEnabled(False)
        self.reduction_spinbox.setEnabled(False)
        self.load_dist_strategy.setEnabled(False)
        
        # Reset dynamic threshold if using dynamic strategy (only on first start)
        if self.load_distribution_strategy == LoadDistributionStrategy.DYNAMIC_THRESHOLD_RELIABILITY_SENSITIVE:
            print(f"[DEBUG] Resetting threshold to initial: {self.initial_load_threshold}")
            self.load_threshold = self.initial_load_threshold
        
        # Initialize logging
        self.load_history = {}
        self.redistribution_log = []
        switches = [c for c in self.components.values() if c.type == ComponentType.SWITCH]
        for switch in switches:
            self.load_history[switch.id] = []
        
        self.calculate_switch_loads(include_requests=True)  # Start including request load
        
        # Log initial state
        for switch in switches:
            self.load_history[switch.id].append((self.simulation_time, switch.current_load))
        
        self.update_statistics()  # Show initial stats
        self.sim_timer.start(500)  # Update every 500ms
    
    def toggle_pause_simulation(self):
        """Pause or resume simulation."""
        if not self.simulation_running:
            return
        self.simulation_paused = not self.simulation_paused
    
    def stop_simulation(self):
        """Stop network simulation."""
        self.simulation_running = False
        self.simulation_paused = False
        self.sim_timer.stop()
        
        # Re-enable threshold, reduction spinboxes and strategy selector
        self.threshold_spinbox.setEnabled(True)
        self.reduction_spinbox.setEnabled(True)
        self.load_dist_strategy.setEnabled(True)
    
    def run_simulation_step(self):
        """Execute one simulation step."""
        self.simulation_time += 1
        
        # Skip simulation updates if paused, but still update display
        if not self.simulation_paused:
            # Accumulate request load for switches each second
            # increment = incoming_requests × (connected_servers + connected_sans) × 0.1
            for component in self.components.values():
                if component.type == ComponentType.SWITCH:
                    num_servers = sum(1 for neighbor_id in component.connections 
                                    if self.components.get(neighbor_id) and 
                                    self.components[neighbor_id].type == ComponentType.SERVER)
                    num_sans = sum(1 for neighbor_id in component.connections 
                                  if self.components.get(neighbor_id) and 
                                  self.components[neighbor_id].type == ComponentType.SAN)
                    total_endpoints = num_servers + num_sans
                    increment = component.incoming_requests * total_endpoints * 0.1
                    component.cumulative_request_load += increment
                    
                    # Increment operational time and calculate reliability using AFTM
                    component.operational_time += 0.5  # 500ms tick
                    # Reliability: R(t,L) = exp(-lambda * t * L^alpha)
                    component.reliability = reliability_R(
                        component.operational_time,
                        component.current_load,
                        component.base_lambda,
                        component.alpha
                    )
            
            # Recalculate loads after request increment (include_requests=True during simulation)
            self.calculate_switch_loads(include_requests=True)
            
            # Apply load distribution strategy if enabled
            if self.load_distribution_strategy == LoadDistributionStrategy.STATIC_THRESHOLD_RELIABILITY_SENSITIVE:
                self.apply_static_threshold_redistribution()
            elif self.load_distribution_strategy == LoadDistributionStrategy.STATIC_THRESHOLD_LOAD_SENSITIVE:
                self.apply_static_threshold_load_sensitive_redistribution()
            elif self.load_distribution_strategy == LoadDistributionStrategy.DYNAMIC_THRESHOLD_RELIABILITY_SENSITIVE:
                self.apply_dynamic_threshold_reliability_sensitive_redistribution()
            elif self.load_distribution_strategy == LoadDistributionStrategy.DYNAMIC_THRESHOLD_LOAD_SENSITIVE:
                self.apply_dynamic_threshold_load_sensitive_redistribution()
        
        # Update graphics and stats
        self.scene.update()
        self.update_statistics()
    
    def apply_static_threshold_redistribution(self):
        """Apply static threshold reliability-sensitive load redistribution.
        
        Logic:
        - If any load >= threshold: trigger redistribution
        - Select top K switches with LOWEST reliability (that have neighbors)
        - Redistribute load from those selected switches
        - If all below threshold after redistribution: success
        - If still above after 4 iterations: show failure dialog and PAUSE
        """
        switches = [c for c in self.components.values() if c.type == ComponentType.SWITCH]
        
        # Find switches over threshold
        switches_over = [s for s in switches if s.current_load >= self.load_threshold]
        
        if not switches_over:
            # Clear over_threshold flag for all if none are over
            for s in switches:
                s.over_threshold = False
            return  # No redistribution needed
        
        print(f"[DEBUG] Redistribution triggered! Switches over threshold: {[s.id for s in switches_over]}")
        print(f"[DEBUG] Top K setting: {self.top_k}")
        
        # Build neighbors map from actual network connections
        neighbors_map = {}
        for switch in switches:
            neighbors_map[switch.id] = [neighbor_id for neighbor_id in switch.connections 
                                        if self.components.get(neighbor_id) and 
                                        self.components[neighbor_id].type == ComponentType.SWITCH]
        
        # Build degrees dictionary (number of connected switches)
        degrees = {s.id: len(neighbors_map[s.id]) for s in switches}
        
        # Check if ANY switch can actually redistribute (has neighbors)
        any_can_redistribute = any(degrees[s.id] > 0 for s in switches)
        
        if not any_can_redistribute:
            # No switches can redistribute - PAUSE and show failure dialog
            for s in switches_over:
                s.over_threshold = True
            self.simulation_paused = True
            self.show_failure_dialog(switches_over)
            return
        
        # Try to redistribute (max 4 iterations)
        iteration = 0
        max_iterations = 4
        
        while iteration < max_iterations:
            iteration += 1
            
            # Find current switches over threshold
            switches_over = [s for s in switches if s.current_load >= self.load_threshold]
            
            if not switches_over:
                # SUCCESS: All switches are now below threshold
                for s in switches:
                    s.over_threshold = False
                return  # No pause needed
            
            # Select top K switches with LOWEST reliability that have neighbors
            eligible_switches = [s for s in switches if degrees[s.id] > 0]
            eligible_switches.sort(key=lambda s: s.reliability)  # Lowest reliability first
            top_k_switches = eligible_switches[:min(self.top_k, len(eligible_switches))]
            sources_to_redistribute = [s.id for s in top_k_switches]
            
            print(f"[DEBUG] Iteration {iteration}: Selected switches by lowest reliability: {[s.id for s in top_k_switches]}")
            print(f"[DEBUG] Their loads: {[(s.id, s.current_load) for s in top_k_switches]}")
            print(f"[DEBUG] Their reliabilities: {[(s.id, s.reliability) for s in top_k_switches]}")
            
            if not sources_to_redistribute:
                # No more switches can redistribute - break loop
                break
            
            # Get current loads for redistribution algorithm
            current_loads = {s.id: s.current_load for s in switches}
            
            # Call redistribution algorithm
            try:
                loads_after = proportional_redistribute_sources_full(
                    loads=current_loads.copy(),
                    degrees=degrees,
                    sources=sources_to_redistribute,
                    neighbors_map=neighbors_map,
                    beta=1.0
                )
            except Exception as e:
                print(f"[Error] Redistribution failed: {e}")
                return
            
            # Apply the redistributed loads to switches
            for switch in switches:
                if switch.id in loads_after:
                    new_load = loads_after[switch.id]
                    switch.current_load = new_load
                    
                    # Update cumulative_request_load to match the new load
                    base_load = 0
                    for neighbor_id in switch.connections:
                        neighbor = self.components.get(neighbor_id)
                        if neighbor:
                            if neighbor.type == ComponentType.SERVER:
                                base_load += 20
                            elif neighbor.type == ComponentType.SWITCH:
                                base_load += 5
                            elif neighbor.type == ComponentType.SAN:
                                base_load += 10
                    
                    switch.cumulative_request_load = max(0, new_load - base_load)
                    
                    # Recalculate reliability with new load
                    switch.reliability = reliability_R(
                        switch.operational_time,
                        switch.current_load,
                        switch.base_lambda,
                        switch.alpha
                    )
        
        # Log redistribution event
        switched_ids = [s for s in switches_over]
        switch_names = ", ".join([s.id for s in switched_ids])
        self.redistribution_log.append((
            self.simulation_time,
            f"Redistribution (iteration {iteration}): {switch_names}"
        ))
        
        # After loop: check if all are below threshold
        switches_still_over = [s for s in switches if s.current_load >= self.load_threshold]
        
        # Mark switches as over_threshold
        for s in switches:
            s.over_threshold = (s.current_load >= self.load_threshold)
        
        if switches_still_over:
            # FAILURE: Still above threshold after 4 iterations - PAUSE and show failure dialog
            self.simulation_paused = True
            self.show_failure_dialog(switches_still_over)
    
    def apply_static_threshold_load_sensitive_redistribution(self):
        """Apply static threshold load-sensitive load redistribution.
        
        Logic:
        - If any load >= threshold: trigger redistribution
        - Select top K switches with HIGHEST load (that have neighbors)
        - Redistribute load from those selected switches
        - If all below threshold after redistribution: success
        - If still above after 4 iterations: show failure dialog and PAUSE
        """
        switches = [c for c in self.components.values() if c.type == ComponentType.SWITCH]
        
        # Find switches over threshold
        switches_over = [s for s in switches if s.current_load >= self.load_threshold]
        
        if not switches_over:
            # Clear over_threshold flag for all if none are over
            for s in switches:
                s.over_threshold = False
            return  # No redistribution needed
        
        print(f"[DEBUG] Load-Sensitive Redistribution triggered! Switches over threshold: {[s.id for s in switches_over]}")
        print(f"[DEBUG] Top K setting: {self.top_k}")
        
        # Build neighbors map from actual network connections
        neighbors_map = {}
        for switch in switches:
            neighbors_map[switch.id] = [neighbor_id for neighbor_id in switch.connections 
                                        if self.components.get(neighbor_id) and 
                                        self.components[neighbor_id].type == ComponentType.SWITCH]
        
        # Build degrees dictionary (number of connected switches)
        degrees = {s.id: len(neighbors_map[s.id]) for s in switches}
        
        # Check if ANY switch can actually redistribute (has neighbors)
        any_can_redistribute = any(degrees[s.id] > 0 for s in switches)
        
        if not any_can_redistribute:
            # No switches can redistribute - PAUSE and show failure dialog
            for s in switches_over:
                s.over_threshold = True
            self.simulation_paused = True
            self.show_failure_dialog(switches_over)
            return
        
        # Try to redistribute (max 4 iterations)
        iteration = 0
        max_iterations = 4
        
        while iteration < max_iterations:
            iteration += 1
            
            # Find current switches over threshold
            switches_over = [s for s in switches if s.current_load >= self.load_threshold]
            
            if not switches_over:
                # SUCCESS: All switches are now below threshold
                for s in switches:
                    s.over_threshold = False
                return  # No pause needed
            
            # Select top K switches with HIGHEST load that have neighbors
            eligible_switches = [s for s in switches if degrees[s.id] > 0]
            eligible_switches.sort(key=lambda s: s.current_load, reverse=True)  # Highest load first
            top_k_switches = eligible_switches[:min(self.top_k, len(eligible_switches))]
            sources_to_redistribute = [s.id for s in top_k_switches]
            
            print(f"[DEBUG] Iteration {iteration}: Selected switches by highest load: {[s.id for s in top_k_switches]}")
            print(f"[DEBUG] Their loads: {[(s.id, s.current_load) for s in top_k_switches]}")
            
            if not sources_to_redistribute:
                # No more switches can redistribute - break loop
                break
            
            # Get current loads for redistribution algorithm
            current_loads = {s.id: s.current_load for s in switches}
            
            # Call redistribution algorithm
            try:
                loads_after = proportional_redistribute_sources_full(
                    loads=current_loads.copy(),
                    degrees=degrees,
                    sources=sources_to_redistribute,
                    neighbors_map=neighbors_map,
                    beta=1.0
                )
            except Exception as e:
                print(f"[Error] Redistribution failed: {e}")
                return
            
            # Apply the redistributed loads to switches
            for switch in switches:
                if switch.id in loads_after:
                    new_load = loads_after[switch.id]
                    switch.current_load = new_load
                    
                    # Update cumulative_request_load to match the new load
                    base_load = 0
                    for neighbor_id in switch.connections:
                        neighbor = self.components.get(neighbor_id)
                        if neighbor:
                            if neighbor.type == ComponentType.SERVER:
                                base_load += 20
                            elif neighbor.type == ComponentType.SWITCH:
                                base_load += 5
                            elif neighbor.type == ComponentType.SAN:
                                base_load += 10
                    
                    switch.cumulative_request_load = max(0, new_load - base_load)
                    
                    # Recalculate reliability with new load
                    switch.reliability = reliability_R(
                        switch.operational_time,
                        switch.current_load,
                        switch.base_lambda,
                        switch.alpha
                    )
        
        # Log redistribution event
        switched_ids = [s for s in switches_over]
        switch_names = ", ".join([s.id for s in switched_ids])
        self.redistribution_log.append((
            self.simulation_time,
            f"Load-Sensitive Redistribution (iteration {iteration}): {switch_names}"
        ))
        
        # After loop: check if all are below threshold
        switches_still_over = [s for s in switches if s.current_load >= self.load_threshold]
        
        # Mark switches as over_threshold
        for s in switches:
            s.over_threshold = (s.current_load >= self.load_threshold)
        
        if switches_still_over:
            # FAILURE: Still above threshold after 4 iterations - PAUSE and show failure dialog
            self.simulation_paused = True
            self.show_failure_dialog(switches_still_over)
    
    def apply_dynamic_threshold_load_sensitive_redistribution(self):
        """Apply dynamic threshold load-sensitive load redistribution.
        
        Similar to reliability-sensitive, but after successful redistribution, 
        the threshold is reduced by dynamic_threshold_reduction amount.
        Selects switches with HIGHEST load to redistribute.
        
        Logic:
        - If load >= threshold: try redistribution (max 4 iterations)
          - Select top K switches with HIGHEST load that have neighbors
          - If all below threshold after redistribution: 
            - Log success
            - Reduce threshold by dynamic_threshold_reduction (min: dynamic_threshold_minimum)
            - Continue simulation (no pause)
          - If still above after 4 iterations: show failure dialog and PAUSE
        """
        print(f"[DEBUG] apply_dynamic_threshold_load_sensitive_redistribution called with threshold={self.load_threshold:.1f}")
        
        switches = [c for c in self.components.values() if c.type == ComponentType.SWITCH]
        
        # Find switches over threshold
        switches_over = [s for s in switches if s.current_load >= self.load_threshold]
        
        if not switches_over:
            # Clear over_threshold flag for all if none are over
            for s in switches:
                s.over_threshold = False
            return  # No redistribution needed
        
        # Build neighbors map from actual network connections
        neighbors_map = {}
        for switch in switches:
            neighbors_map[switch.id] = [neighbor_id for neighbor_id in switch.connections 
                                        if self.components.get(neighbor_id) and 
                                        self.components[neighbor_id].type == ComponentType.SWITCH]
        
        # Build degrees dictionary (number of connected switches)
        degrees = {s.id: len(neighbors_map[s.id]) for s in switches}
        
        # Check if ANY switch can actually redistribute (has neighbors)
        any_can_redistribute = any(degrees[s.id] > 0 for s in switches)
        
        if not any_can_redistribute:
            # No switches can redistribute - PAUSE and show failure dialog
            for s in switches_over:
                s.over_threshold = True
            self.simulation_paused = True
            self.show_failure_dialog(switches_over)
            return
        
        # Try to redistribute (max 4 iterations)
        iteration = 0
        max_iterations = 4
        
        while iteration < max_iterations:
            iteration += 1
            
            # Find current switches over threshold
            switches_over = [s for s in switches if s.current_load >= self.load_threshold]
            
            if not switches_over:
                # SUCCESS: All switches are now below threshold
                for s in switches:
                    s.over_threshold = False
                
                # Reduce threshold for next redistribution
                old_threshold = self.load_threshold
                self.load_threshold = max(self.dynamic_threshold_minimum, 
                                         self.load_threshold - self.dynamic_threshold_reduction)
                
                print(f"[THRESHOLD] Reduced from {old_threshold:.1f} to {self.load_threshold:.1f} (early success)")
                
                # Update the spinbox to show new threshold
                self.threshold_spinbox.blockSignals(True)
                self.threshold_spinbox.setValue(int(self.load_threshold))
                self.threshold_spinbox.blockSignals(False)
                
                # Log success
                self.redistribution_log.append((
                    self.simulation_time,
                    f"Redistribution successful (dynamic load-sensitive). New threshold: {self.load_threshold:.1f}"
                ))
                
                return  # No pause needed
            
            # Filter switches with neighbors that can redistribute
            eligible_switches = [s for s in switches if degrees[s.id] > 0]
            eligible_switches.sort(key=lambda s: s.current_load, reverse=True)  # Highest load first
            
            # Select top K switches with highest load (load-sensitive)
            top_k_switches = eligible_switches[:min(self.top_k, len(eligible_switches))]
            sources_to_redistribute = [s.id for s in top_k_switches]
            
            if not sources_to_redistribute:
                # No more switches can redistribute - break loop
                break
            
            # Get current loads for redistribution algorithm
            current_loads = {s.id: s.current_load for s in switches}
            
            # Call redistribution algorithm
            try:
                loads_after = proportional_redistribute_sources_full(
                    loads=current_loads.copy(),
                    degrees=degrees,
                    sources=sources_to_redistribute,
                    neighbors_map=neighbors_map,
                    beta=1.0
                )
            except Exception as e:
                print(f"[Error] Redistribution failed: {e}")
                return
            
            # Apply the redistributed loads to switches
            for switch in switches:
                if switch.id in loads_after:
                    new_load = loads_after[switch.id]
                    switch.current_load = new_load
                    
                    # Update cumulative_request_load to match the new load
                    base_load = 0
                    for neighbor_id in switch.connections:
                        neighbor = self.components.get(neighbor_id)
                        if neighbor:
                            if neighbor.type == ComponentType.SERVER:
                                base_load += 20
                            elif neighbor.type == ComponentType.SWITCH:
                                base_load += 5
                            elif neighbor.type == ComponentType.SAN:
                                base_load += 10
                    
                    switch.cumulative_request_load = max(0, new_load - base_load)
                    
                    # Recalculate reliability with new load
                    switch.reliability = reliability_R(
                        switch.operational_time,
                        switch.current_load,
                        switch.base_lambda,
                        switch.alpha
                    )
            
            # Log this iteration
            self.redistribution_log.append((
                self.simulation_time,
                f"Redistribution iteration {iteration} (dynamic load-sensitive)."
            ))
        
        # After loop: check if all are below threshold
        switches_still_over = [s for s in switches if s.current_load >= self.load_threshold]
        
        # Mark switches as over_threshold
        for s in switches:
            s.over_threshold = (s.current_load >= self.load_threshold)
        
        if not switches_still_over:
            # SUCCESS: All switches are below threshold after loop iterations
            # Reduce threshold only once after successful redistribution
            old_threshold = self.load_threshold
            self.load_threshold = max(self.dynamic_threshold_minimum, 
                                     self.load_threshold - self.dynamic_threshold_reduction)
            
            print(f"[THRESHOLD] Reduced from {old_threshold:.1f} to {self.load_threshold:.1f} (after loop)")
            
            # Update the spinbox to show new threshold
            self.threshold_spinbox.blockSignals(True)
            self.threshold_spinbox.setValue(int(self.load_threshold))
            self.threshold_spinbox.blockSignals(False)
            
            # Log success
            self.redistribution_log.append((
                self.simulation_time,
                f"Redistribution successful (dynamic load-sensitive). New threshold: {self.load_threshold:.1f}"
            ))
        else:
            # FAILURE: Still above threshold after 4 iterations - PAUSE and show failure dialog
            self.simulation_paused = True
            self.show_failure_dialog(switches_still_over)
    
    def show_failure_dialog(self, switches_over):
        """Show failure dialog when redistribution is not possible or failed."""
        dialog = QMessageBox(self)
        dialog.setWindowTitle("Redistribution Failed")
        dialog.setIcon(QMessageBox.Icon.Warning)
        
        switch_names = ", ".join([s.id for s in switches_over])
        message = f"Redistribution failed for: {switch_names}\n\n" \
                  f"Load is still above threshold ({self.load_threshold}).\n\n" \
                  f"Options:\n" \
                  f"1. Increase the threshold\n" \
                  f"2. Add a new switch and connect it to relieve the load\n\n" \
                  f"Simulation is paused. Please take action and try again."
        
        dialog.setText(message)
        dialog.setStandardButtons(QMessageBox.StandardButton.Ok)
        dialog.exec()
    
    def apply_dynamic_threshold_reliability_sensitive_redistribution(self):
        """Apply dynamic threshold reliability-sensitive load redistribution.
        
        Similar to static threshold, but after successful redistribution, 
        the threshold is reduced by dynamic_threshold_reduction amount.
        Selects switches with LOWEST reliability to redistribute.
        
        Logic:
        - If load >= threshold: try redistribution (max 4 iterations)
          - Select top K switches with LOWEST reliability that have neighbors
          - If all below threshold after redistribution: 
            - Log success
            - Reduce threshold by dynamic_threshold_reduction (min: dynamic_threshold_minimum)
            - Continue simulation (no pause)
          - If still above after 4 iterations: show failure dialog and PAUSE
        """
        print(f"[DEBUG] apply_dynamic_threshold_reliability_sensitive_redistribution called with threshold={self.load_threshold:.1f}")
        
        switches = [c for c in self.components.values() if c.type == ComponentType.SWITCH]
        
        # Find switches over threshold
        switches_over = [s for s in switches if s.current_load >= self.load_threshold]
        
        if not switches_over:
            # Clear over_threshold flag for all if none are over
            for s in switches:
                s.over_threshold = False
            return  # No redistribution needed
        
        # Build neighbors map from actual network connections
        neighbors_map = {}
        for switch in switches:
            neighbors_map[switch.id] = [neighbor_id for neighbor_id in switch.connections 
                                        if self.components.get(neighbor_id) and 
                                        self.components[neighbor_id].type == ComponentType.SWITCH]
        
        # Build degrees dictionary (number of connected switches)
        degrees = {s.id: len(neighbors_map[s.id]) for s in switches}
        
        # Check if ANY switch can actually redistribute (has neighbors)
        any_can_redistribute = any(degrees[s.id] > 0 for s in switches)
        
        if not any_can_redistribute:
            # No switches can redistribute - PAUSE and show failure dialog
            for s in switches_over:
                s.over_threshold = True
            self.simulation_paused = True
            self.show_failure_dialog(switches_over)
            return
        
        # Try to redistribute (max 4 iterations)
        iteration = 0
        max_iterations = 4
        
        while iteration < max_iterations:
            iteration += 1
            
            # Find current switches over threshold
            switches_over = [s for s in switches if s.current_load >= self.load_threshold]
            
            if not switches_over:
                # SUCCESS: All switches are now below threshold
                for s in switches:
                    s.over_threshold = False
                
                # Reduce threshold for next redistribution
                old_threshold = self.load_threshold
                self.load_threshold = max(self.dynamic_threshold_minimum, 
                                         self.load_threshold - self.dynamic_threshold_reduction)
                
                print(f"[THRESHOLD] Reduced from {old_threshold:.1f} to {self.load_threshold:.1f} (early success)")
                
                # Update the spinbox to show new threshold
                self.threshold_spinbox.blockSignals(True)
                self.threshold_spinbox.setValue(int(self.load_threshold))
                self.threshold_spinbox.blockSignals(False)
                
                # Log success
                self.redistribution_log.append((
                    self.simulation_time,
                    f"Redistribution successful (dynamic reliability-sensitive). New threshold: {self.load_threshold:.1f}"
                ))
                
                return  # No pause needed
            
            # Filter switches with neighbors that can redistribute
            eligible_switches = [s for s in switches if degrees[s.id] > 0]
            eligible_switches.sort(key=lambda s: s.reliability)  # Lowest reliability first
            
            # Select top K switches with lowest reliability (reliability-sensitive)
            top_k_switches = eligible_switches[:min(self.top_k, len(eligible_switches))]
            sources_to_redistribute = [s.id for s in top_k_switches]
            
            if not sources_to_redistribute:
                # No more switches can redistribute - break loop
                break
            
            # Get current loads for redistribution algorithm
            current_loads = {s.id: s.current_load for s in switches}
            
            # Call redistribution algorithm
            try:
                loads_after = proportional_redistribute_sources_full(
                    loads=current_loads.copy(),
                    degrees=degrees,
                    sources=sources_to_redistribute,
                    neighbors_map=neighbors_map,
                    beta=1.0
                )
            except Exception as e:
                print(f"[Error] Redistribution failed: {e}")
                return
            
            # Apply the redistributed loads to switches
            for switch in switches:
                if switch.id in loads_after:
                    new_load = loads_after[switch.id]
                    switch.current_load = new_load
                    
                    # Update cumulative_request_load to match the new load
                    base_load = 0
                    for neighbor_id in switch.connections:
                        neighbor = self.components.get(neighbor_id)
                        if neighbor:
                            if neighbor.type == ComponentType.SERVER:
                                base_load += 20
                            elif neighbor.type == ComponentType.SWITCH:
                                base_load += 5
                            elif neighbor.type == ComponentType.SAN:
                                base_load += 10
                    
                    switch.cumulative_request_load = max(0, new_load - base_load)
                    
                    # Recalculate reliability with new load
                    switch.reliability = reliability_R(
                        switch.operational_time,
                        switch.current_load,
                        switch.base_lambda,
                        switch.alpha
                    )
            
            # Log this iteration
            self.redistribution_log.append((
                self.simulation_time,
                f"Redistribution iteration {iteration} (dynamic reliability-sensitive)."
            ))
        
        # After loop: check if all are below threshold
        switches_still_over = [s for s in switches if s.current_load >= self.load_threshold]
        
        # Mark switches as over_threshold
        for s in switches:
            s.over_threshold = (s.current_load >= self.load_threshold)
        
        if not switches_still_over:
            # SUCCESS: All switches are below threshold after loop iterations
            # Reduce threshold only once after successful redistribution
            old_threshold = self.load_threshold
            self.load_threshold = max(self.dynamic_threshold_minimum, 
                                     self.load_threshold - self.dynamic_threshold_reduction)
            
            print(f"[THRESHOLD] Reduced from {old_threshold:.1f} to {self.load_threshold:.1f} (after loop)")
            
            # Update the spinbox to show new threshold
            self.threshold_spinbox.blockSignals(True)
            self.threshold_spinbox.setValue(int(self.load_threshold))
            self.threshold_spinbox.blockSignals(False)
            
            # Log success
            self.redistribution_log.append((
                self.simulation_time,
                f"Redistribution successful (dynamic reliability-sensitive). New threshold: {self.load_threshold:.1f}"
            ))
        else:
            # FAILURE: Still above threshold after 4 iterations - PAUSE and show failure dialog
            self.simulation_paused = True
            self.show_failure_dialog(switches_still_over)
    
    def update_statistics(self):
        """Update statistics table - switches only."""
        # Get all switches
        switches = [c for c in self.components.values() if c.type == ComponentType.SWITCH]
        
        # Ensure table has the right number of rows
        if self.stats_table.rowCount() != len(switches):
            self.stats_table.blockSignals(True)
            self.stats_table.setRowCount(len(switches))
            
            for row, switch in enumerate(switches):
                # Switch ID (not editable)
                id_item = QTableWidgetItem(switch.id)
                id_item.setFlags(id_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self.stats_table.setItem(row, 0, id_item)
                
                # Req/s: editable for user to pause and adjust
                req_item = QTableWidgetItem(str(int(switch.incoming_requests)))
                req_item.setFlags(req_item.flags() | Qt.ItemFlag.ItemIsEditable)
                self.stats_table.setItem(row, 2, req_item)
                
                # Lambda: editable
                lambda_item = QTableWidgetItem(f"{switch.base_lambda:.2e}")
                lambda_item.setFlags(lambda_item.flags() | Qt.ItemFlag.ItemIsEditable)
                self.stats_table.setItem(row, 4, lambda_item)
                
                # Alpha: editable
                alpha_item = QTableWidgetItem(str(switch.alpha))
                alpha_item.setFlags(alpha_item.flags() | Qt.ItemFlag.ItemIsEditable)
                self.stats_table.setItem(row, 5, alpha_item)
            
            self.stats_table.blockSignals(False)
        
        # Update Load, Reliability, and Op.Time on every frame
        for row, switch in enumerate(switches):
            # Load (update only) - just the numeric value
            load_text = f"{switch.current_load:.1f}"
            load_item = self.stats_table.item(row, 1)
            if load_item is None:
                load_item = QTableWidgetItem(load_text)
                load_item.setFlags(load_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self.stats_table.setItem(row, 1, load_item)
            else:
                load_item.setText(load_text)
            
            # Reliability (update only) - AFTM-based reliability
            reliability_text = f"{switch.reliability:.4f}"
            reliability_item = self.stats_table.item(row, 3)
            if reliability_item is None:
                reliability_item = QTableWidgetItem(reliability_text)
                reliability_item.setFlags(reliability_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self.stats_table.setItem(row, 3, reliability_item)
            else:
                reliability_item.setText(reliability_text)
            
            # Operational Time (update only)
            op_time_text = f"{switch.operational_time:.1f}s"
            op_time_item = self.stats_table.item(row, 6)
            if op_time_item is None:
                op_time_item = QTableWidgetItem(op_time_text)
                op_time_item.setFlags(op_time_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self.stats_table.setItem(row, 6, op_time_item)
            else:
                op_time_item.setText(op_time_text)
        
        # Log current loads for graph generation (only during simulation, every 5 seconds)
        if self.simulation_running and not self.simulation_paused:
            self.log_counter += 1
            if self.log_counter >= 10:  # 10 ticks × 500ms = 5 seconds
                self.log_counter = 0
                for switch in switches:
                    if switch.id in self.load_history:
                        self.load_history[switch.id].append((self.simulation_time, switch.current_load))
        
        # Update graphics for all switches to reflect color changes (over_threshold, load colors)
        for graphics_item in self.graphics_items.values():
            if graphics_item.component.type == ComponentType.SWITCH:
                graphics_item.update()
    
    def on_stats_cell_changed(self, row: int, column: int):
        """Handle edits in the statistics table (Req/s, Lambda, Alpha for switches)."""
        id_item = self.stats_table.item(row, 0)
        if id_item is None:
            return
        
        comp_id = id_item.text()
        comp = self.components.get(comp_id)
        if comp is None or comp.type != ComponentType.SWITCH:
            return
        
        value_item = self.stats_table.item(row, column)
        if value_item is None:
            return
        
        try:
            # Column 2: Req/s (incoming requests)
            if column == 2:
                val = float(value_item.text())
                if val < 0:
                    val = 0
                comp.incoming_requests = val
            
            # Column 4: Lambda (base failure rate)
            elif column == 4:
                val = float(value_item.text())
                if val < 0:
                    val = 0
                comp.base_lambda = val
            
            # Column 5: Alpha (load exponent)
            elif column == 5:
                val = float(value_item.text())
                if val < 0:
                    val = 0
                comp.alpha = val
            
            else:
                return
        except Exception:
            return
        
        # Recalculate loads and reliability immediately when user edits
        self.calculate_switch_loads(include_requests=self.simulation_running)
    
    def generate_graph(self):
        """Generate and display load vs time graph for all switches."""
        # Get all current switches
        all_switches = [c for c in self.components.values() if c.type == ComponentType.SWITCH]
        
        if not all_switches:
            QMessageBox.warning(self, "No Data", "No switches in the network")
            return
        
        # Check if we have any load history data
        has_history = any(self.load_history.get(s.id, []) for s in all_switches)
        
        if not has_history:
            QMessageBox.warning(self, "No Data", "Run simulation first to generate graph")
            return
        
        # Create figure
        plt.figure(figsize=(12, 6))
        
        # Plot load for each switch from history
        colors = ['blue', 'red', 'green', 'orange', 'purple', 'brown', 'pink', 'gray']
        plotted = False
        
        for i, switch in enumerate(all_switches):
            history = self.load_history.get(switch.id, [])
            if history:  # Plot if there's history data
                times = [t for t, _ in history]
                loads = [l for _, l in history]
                color = colors[i % len(colors)]
                plt.plot(times, loads, marker='o', label=switch.id, color=color, linewidth=2)
                plotted = True
        
        if not plotted:
            QMessageBox.warning(self, "No Data", "No load history recorded")
            return
        
        plt.xlabel('Time (steps)', fontsize=12)
        plt.ylabel('Load', fontsize=12)
        plt.title('Switch Load vs Time', fontsize=14, fontweight='bold')
        plt.legend(loc='best')
        plt.grid(True, alpha=0.3)
        plt.tight_layout()
        
        # Show the plot
        plt.show()
    
    def clear_all(self):
        """Clear all components and connections."""
        reply = QMessageBox.question(self, "Confirm", "Clear all components?", 
                                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if reply == QMessageBox.StandardButton.Yes:
            self.scene.clear()
            self.components.clear()
            self.graphics_items.clear()
            self.connections_graphics.clear()
    
    def save_configuration(self):
        """Save network configuration to JSON."""
        config = {
            'components': [c.to_dict() for c in self.components.values()],
            'load_balancing_strategy': self.load_balancer.strategy.value
        }
        
        try:
            with open('network_config.json', 'w') as f:
                json.dump(config, f, indent=2)
            QMessageBox.information(self, "Saved", "Configuration saved to network_config.json")
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to save: {str(e)}")
    
    def load_configuration(self):
        """Load network configuration from JSON."""
        try:
            with open('network_config.json', 'r') as f:
                config = json.load(f)
            
            self.clear_all()
            
            # Load components
            for comp_data in config['components']:
                comp_type = ComponentType(comp_data['type'])
                component = NetworkComponent(comp_type, comp_data['x'], comp_data['y'])
                component.id = comp_data['id']
                # Restore incoming requests if present
                component.incoming_requests = comp_data.get('incoming_requests', 0)
                # Restore cumulative request load if present
                component.cumulative_request_load = comp_data.get('cumulative_request_load', 0.0)
                # Restore AFTM parameters if present
                component.operational_time = comp_data.get('operational_time', 0.0)
                component.base_lambda = comp_data.get('base_lambda', 3e-6)
                component.alpha = comp_data.get('alpha', 1.0)
                self.components[component.id] = component
                
                graphics_item = GraphicsNetworkComponent(component)
                self.graphics_items[component.id] = graphics_item
                self.scene.addItem(graphics_item)
            
            # Restore connections
            for comp_data in config['components']:
                source = self.components[comp_data['id']]
                for dest_id in comp_data['connections']:
                    source.connect_to(dest_id)
                    
                    # Add graphics connections
                    if source.id in self.graphics_items and dest_id in self.graphics_items:
                        conn = GraphicsConnection(self.graphics_items[source.id], 
                                                self.graphics_items[dest_id])
                        self.connections_graphics.append(conn)
                        self.scene.addItem(conn)
            
            QMessageBox.information(self, "Loaded", "Configuration loaded successfully")
        except FileNotFoundError:
            QMessageBox.warning(self, "Error", "Configuration file not found")
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to load: {str(e)}")


def main():
    app = QApplication(sys.argv)
    simulator = NetworkSimulator()
    simulator.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
