"""Small visual editor that emits the shared deterministic rule AST."""

from PySide6.QtWidgets import QCheckBox, QComboBox, QGroupBox, QHBoxLayout, QLineEdit, QPushButton, QVBoxLayout, QWidget

from contextvault.query.ast import All, Any, Not, Predicate
from contextvault.query.validation import validate


class RuleBuilder(QWidget):
    FIELDS = ("content", "extension", "name", "path", "mime", "tag", "size", "modified")

    def __init__(self, parent=None):
        super().__init__(parent)
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(0, 0, 0, 0)
        self.rows = []
        self.groups = []
        controls = QHBoxLayout()
        self.match_mode = QComboBox()
        self.match_mode.addItems(["All (AND)", "Any (OR)"])
        self.negate_group = QCheckBox("Exclude matching group (NOT)")
        self.add_button = QPushButton("Add condition")
        self.add_button.clicked.connect(self.add_condition)
        self.add_group_button = QPushButton("Add nested group")
        self.add_group_button.clicked.connect(self.add_group)
        controls.addWidget(self.match_mode)
        controls.addWidget(self.negate_group)
        controls.addWidget(self.add_button)
        controls.addWidget(self.add_group_button)
        controls.addStretch()
        self.layout.addLayout(controls)

    def add_condition(self, field="content", op=None, value=""):
        row = QHBoxLayout()
        field_box = QComboBox()
        field_box.addItems(self.FIELDS)
        field_box.setCurrentText(field)
        op_box = QComboBox()
        op_box.addItems(["contains", "phrase", "regex", "eq", "ne", "gt", "gte", "lt", "lte"])
        if op:
            op_box.setCurrentText(op)
        value_edit = QLineEdit(str(value))
        value_edit.setPlaceholderText("Value")
        remove = QPushButton("Remove")
        row.addWidget(field_box)
        row.addWidget(op_box)
        row.addWidget(value_edit, 1)
        row.addWidget(remove)
        self.layout.insertLayout(self.layout.count() - 1, row)
        item = (row, field_box, op_box, value_edit)
        self.rows.append(item)
        remove.clicked.connect(lambda: self.remove_condition(item))
        return item

    def remove_condition(self, item):
        if item not in self.rows:
            return
        self.rows.remove(item)
        row = item[0]
        while row.count():
            child = row.takeAt(0)
            widget = child.widget()
            if widget:
                widget.deleteLater()

    def add_group(self):
        box = QGroupBox("Nested group")
        box_layout = QVBoxLayout(box)
        group_controls = QHBoxLayout()
        mode = QComboBox()
        mode.addItems(["All (AND)", "Any (OR)"])
        negate = QCheckBox("NOT")
        add = QPushButton("Add condition")
        group_controls.addWidget(mode)
        group_controls.addWidget(negate)
        group_controls.addWidget(add)
        group_controls.addStretch()
        box_layout.addLayout(group_controls)
        rows = []
        self.layout.insertWidget(self.layout.count() - 1, box)
        def add_row(field_value="content", op_value=None, text_value=""):
            row = QHBoxLayout()
            field = QComboBox()
            field.addItems(self.FIELDS)
            field.setCurrentText(field_value)
            op = QComboBox()
            op.addItems(["contains", "phrase", "regex", "eq", "ne", "gt", "gte", "lt", "lte"])
            if op_value:
                op.setCurrentText(op_value)
            value = QLineEdit()
            value.setText(str(text_value))
            value.setPlaceholderText("Value")
            remove = QPushButton("Remove")
            row.addWidget(field)
            row.addWidget(op)
            row.addWidget(value, 1)
            row.addWidget(remove)
            box_layout.insertLayout(box_layout.count(), row)
            data = (row, field, op, value)
            rows.append(data)
            remove.clicked.connect(lambda: self._remove_group_row(rows, data))
        add.clicked.connect(lambda checked=False: add_row())
        group = (box, mode, negate, rows)
        self.groups.append(group)
        return group

    @staticmethod
    def _remove_group_row(rows, item):
        if item not in rows:
            return
        rows.remove(item)
        row = item[0]
        while row.count():
            child = row.takeAt(0)
            widget = child.widget()
            if widget:
                widget.deleteLater()

    def build_rule(self):
        children = [validate(Predicate(field.currentText(), op.currentText(), value.text()))
                    for _, field, op, value in self.rows if value.text().strip()]
        for _, mode, negate, rows in self.groups:
            nested = tuple(validate(Predicate(field.currentText(), op.currentText(), value.text()))
                           for _, field, op, value in rows if value.text().strip())
            if nested:
                node = All(nested) if mode.currentIndex() == 0 else Any(nested)
                children.append(Not(node) if negate.isChecked() else node)
        children = tuple(children)
        if not children:
            return None
        root = All(children) if self.match_mode.currentIndex() == 0 else Any(children)
        return Not(root) if self.negate_group.isChecked() else root
