#!/usr/bin/env python
#
# Electrum - lightweight Bitcoin client
# Copyright (C) 2015 Thomas Voegtlin
# Copyright 2019 Bitcoin Association
#
# Permission is hereby granted, free of charge, to any person
# obtaining a copy of this software and associated documentation files
# (the "Software"), to deal in the Software without restriction,
# including without limitation the rights to use, copy, modify, merge,
# publish, distribute, sublicense, and/or sell copies of the Software,
# and to permit persons to whom the Software is furnished to do so,
# subject to the following conditions:
#
# The above copyright notice and this permission notice shall be
# included in all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND,
# EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF
# MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND
# NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS
# BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN
# ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN
# CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.

from collections import namedtuple
from functools import partial
import time
from typing import Any, List
import webbrowser

from PyQt5.QtCore import QAbstractItemModel, QModelIndex, QVariant, Qt, QSortFilterProxyModel
from PyQt5.QtGui import QFont, QBrush, QColor
from PyQt5.QtWidgets import QTableView, QAbstractItemView, QHeaderView, QMenu

from electrumsv.app_state import app_state
from electrumsv.i18n import _
from electrumsv.logs import logs
from electrumsv.platform import platform
from electrumsv.transaction import Transaction
from electrumsv.util import timestamp_to_datetime, profiler, format_time
from electrumsv.wallet import Abstract_Wallet
import electrumsv.web as web

from .util import read_QIcon, get_source_index


logger = logs.get_logger("history-list")

TX_ICONS = [
    "unconfirmed.png",
    "unconfirmed.png",
    "unconfirmed.png",
    "unconfirmed.png",
    "clock1.png",
    "clock2.png",
    "clock3.png",
    "clock4.png",
    "clock5.png",
    "confirmed.png",
]

TX_STATUS = [
    _('Unconfirmed parent'),
    _('Unconfirmed'),
    _('Not Verified'),
]

COLUMN_NAMES = ['', _('Date'), _('Description') , _('Amount'), _('Balance'), '', '']

ICON_COLUMN = 0
STATUS_COLUMN = 1
DESCRIPTION_COLUMN = 2
AMOUNT_COLUMN = 3
BALANCE_COLUMN = 4
FIAT_AMOUNT_COLUMN = 5
FIAT_BALANCE_COLUMN = 6

QT_SORT_ROLE = Qt.UserRole+1


class HistoryLine(namedtuple("HistoryLine", "tx_hash, height, conf, timestamp, value, balance, "+
        "status")):
    pass


LI_HASH = 0
LI_HEIGHT = 1
LI_CONF = 2
LI_TIMESTAMP = 3
LI_VALUE = 4
LI_BALANCE = 5


class HistoryItemModel(QAbstractItemModel):
    def __init__(self, parent: Any, column_names: List[str], data: List[HistoryLine]) -> None:
        super().__init__(parent)

        self._view = parent
        self._data = data
        self._column_names = column_names

        self._monospace_font = QFont(platform.monospace_font)
        self._withdrawal_brush = QBrush(QColor("#BC1E1E"))
        self._invoice_icon = read_QIcon("seal")

    def set_column_names(self, column_names: List[str]) -> None:
        self._column_names = column_names[:]

    def set_column_name(self, column_index: int, column_name: str) -> None:
        self._column_names[column_index] = column_name

    def set_data(self, data: List[Any]) -> None:
        self._data = data

    def columnCount(self, model_index: QModelIndex) -> int:
        return len(self._column_names)

    def data(self, model_index: QModelIndex, role: int) -> QVariant:
        row = model_index.row()
        column = model_index.column()
        if row >= len(self._data):
            return None
        if column >= len(self._column_names):
            return None

        if model_index.isValid():
            line = self._data[row]
            # First check the custom sort role.
            if role == QT_SORT_ROLE:
                # Sort based on raw value.
                if column == STATUS_COLUMN:
                    if line.timestamp is False:
                        return 9999999999 - line.status
                    return line.timestamp
                elif column == AMOUNT_COLUMN:
                    return line.value
                elif column == BALANCE_COLUMN:
                    return line.balance
                elif column == FIAT_AMOUNT_COLUMN:
                    return line.value
                elif column == FIAT_BALANCE_COLUMN:
                    return line.balance

                # Just use the displayed text.
                role = Qt.DisplayRole
            if role == Qt.EditRole:
                if column == DESCRIPTION_COLUMN:
                    return self._view._wallet.get_label(line.tx_hash)
            elif role == Qt.DecorationRole:
                if column == ICON_COLUMN:
                    return read_QIcon(TX_ICONS[line.status])
                elif column == AMOUNT_COLUMN:
                    if self._view._wallet.invoices.paid.get(line.tx_hash):
                        return self._invoice_icon
            elif role == Qt.DisplayRole:
                if column == STATUS_COLUMN:
                    return self._view._format_tx_status(line.status, line.timestamp)
                elif column == DESCRIPTION_COLUMN:
                    return self._view._wallet.get_label(line.tx_hash)
                elif column == AMOUNT_COLUMN:
                    return self._view._main_window.format_amount(line.value,
                        True, whitespaces=True)
                elif column == BALANCE_COLUMN:
                    return self._view._main_window.format_amount(line.balance,
                        whitespaces=True)
                elif column >= FIAT_AMOUNT_COLUMN:
                    fx = app_state.fx
                    fx_enabled = fx and fx.show_history()
                    if fx and fx.show_history():
                        if column == FIAT_AMOUNT_COLUMN:
                            date = timestamp_to_datetime(time.time()
                                if line.conf <= 0 else line.timestamp)
                            return app_state.fx.historical_value_str(line.value, date)
                        elif column == FIAT_BALANCE_COLUMN:
                            date = timestamp_to_datetime(time.time()
                                if line.conf <= 0 else line.timestamp)
                            return app_state.fx.historical_value_str(line.balance, date)
            elif role == Qt.FontRole:
                if column != STATUS_COLUMN:
                    return self._monospace_font
            elif role == Qt.ForegroundRole:
                if line.value and line.value < 0:
                    if column == AMOUNT_COLUMN or column == BALANCE_COLUMN:
                        return self._withdrawal_brush
            elif role == Qt.TextAlignmentRole:
                if column == ICON_COLUMN or column >= AMOUNT_COLUMN:
                    return Qt.AlignRight | Qt.AlignVCenter
            elif role == Qt.ToolTipRole:
                suffix = "s" if line.conf != 1 else ""
                return f"{line.conf} confirmation{suffix}"

    def flags(self, model_index: QModelIndex) -> int:
        if model_index.isValid():
            column = model_index.column()
            flags = super().flags(model_index)
            if column == DESCRIPTION_COLUMN:
                flags |= Qt.ItemIsEditable
            return flags
        return Qt.ItemIsEnabled

    def headerData(self, section: int, orientation: int, role: int) -> QVariant:
        if orientation == Qt.Horizontal and role == Qt.DisplayRole:
            if section < len(self._column_names):
                return self._column_names[section]

    def index(self, row: int, column: int, parent: Any) -> QModelIndex:
        if self.hasIndex(row, column, parent):
            return self.createIndex(row, column)
        return QModelIndex()

    def parent(self, model_index: QModelIndex) -> QModelIndex:
        return QModelIndex()

    def rowCount(self, model_index: QModelIndex) -> int:
        return len(self._data)

    def setData(self, model_index: QModelIndex, value: QVariant, role: int) -> bool:
        if model_index.isValid() and role == Qt.EditRole:
            row = model_index.row()
            line = self._data[row]
            self._view._wallet.set_label(line.tx_hash, value)
            self.dataChanged.emit(model_index, model_index)
            return True
        return False


class HistorySortFilterProxyModel(QSortFilterProxyModel):
    def lessThan(self, source_left: QModelIndex, source_right: QModelIndex) -> bool:
        value_left = self.sourceModel().data(source_left, QT_SORT_ROLE)
        value_right = self.sourceModel().data(source_right, QT_SORT_ROLE)
        return value_left < value_right


class BaseView(QTableView):
    def __init__(self, parent: Any) -> None:
        super().__init__(parent)

        self.setVerticalScrollMode(QAbstractItemView.ScrollPerItem)
        self.setSelectionBehavior(QAbstractItemView.SelectItems)
        self.setSelectionMode(QAbstractItemView.SingleSelection)

        self.verticalHeader().setVisible(False)


class HistoryView(BaseView):
    def __init__(self, parent: Any, wallet: Abstract_Wallet) -> None:
        super().__init__(parent)

        self._main_window = parent
        self._wallet = wallet

        self._headers = COLUMN_NAMES

        self.setAlternatingRowColors(True)
        self.sortByColumn(STATUS_COLUMN, Qt.DescendingOrder)

        self._data = self._create_data_snapshot()
        model = HistoryItemModel(self, self._headers, self._data)
        # NOTE: rt12 -- The raw sort model does not appear to be using the sort role.
        # proxy_model = QSortFilterProxyModel()
        # NOTE: rt12 -- This custom sort model implements explcit sort role usage.
        proxy_model = HistorySortFilterProxyModel()
        # If the underlying model changes, observe it in the sort.
        proxy_model.setDynamicSortFilter(True)
        proxy_model.setSortRole(QT_SORT_ROLE)
        proxy_model.setSourceModel(model)
        self.setModel(proxy_model)

        fx = app_state.fx
        self._set_fiat_columns_enabled(fx and fx.show_history())

        self.setSortingEnabled(True)

        self.horizontalHeader().setSectionResizeMode(DESCRIPTION_COLUMN, QHeaderView.Stretch)
        for i in range(FIAT_BALANCE_COLUMN-1):
            if i != DESCRIPTION_COLUMN:
                self.horizontalHeader().setSectionResizeMode(i, QHeaderView.ResizeToContents)
        self.horizontalHeader().setMinimumSectionSize(20)
        self.verticalHeader().setMinimumSectionSize(20)
        self.verticalHeader().resizeSections()
        self.horizontalHeader().resizeSections()

        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self._event_create_menu)

        self._main_window.history_updated_signal.connect(self._on_history_update_event)
        self._main_window.new_transaction_signal.connect(self._on_new_transaction)

        self.setEditTriggers(QAbstractItemView.DoubleClicked)
        self.doubleClicked.connect(self._event_double_clicked)

    # Event from external fx code.
    def update_fx_history(self) -> None:
        fx = app_state.fx
        flag = fx and fx.show_history()

        # This will show or hide the relevant columns as applicable.
        self._set_fiat_columns_enabled(flag)

        # This will notify the model that the relevant cells are changed.
        if flag:
            model = self.model()
            start_index = model.createIndex(0, FIAT_AMOUNT_COLUMN)
            end_index = model.createIndex(model.columnCount(start_index), FIAT_BALANCE_COLUMN)
            model.dataChanged.emit(start_index, end_index)

    def _on_new_transaction(self, tx: Transaction) -> None:
        # What do we do here?
        pass

    def _on_history_update_event(self, event_name: str) -> None:
        # logger.debug(f"_on_history_update_event({event_name})/START")
        if event_name == "fiat_ccy_changed":
            self.update_fx_history()
        elif event_name == "num_zeros_changed" or event_name == "base_unit_changed":
            model = self.model().sourceModel()
            start_index = model.createIndex(0, AMOUNT_COLUMN)
            end_index = model.createIndex(model.rowCount(start_index), BALANCE_COLUMN)
            model.dataChanged.emit(start_index, end_index)
        elif event_name == "delete_invoice":
            self.update_all()
        elif event_name == "import_labels":
            # NOTE: We could optimise this if we had all the labels and tx hashes they were for.
            self.update_all()
        elif event_name == "import_addresses":
            self.update_all()
        elif event_name == "import_privkey":
            self.update_all()
        elif event_name == "update_tabs":
            self.update_all()
        # logger.debug(f"_on_history_update_event({event_name})/END")

    def update_transaction(self, tx_hash: str) -> None:
        logger.debug(f"update_transaction({tx_hash})")
        height, conf, timestamp = self._wallet.get_tx_height(tx_hash)
        self.update_line(tx_hash, height, conf, timestamp)

    def update_line(self, tx_hash: str, height: int, conf: int, timestamp: int) -> None:
        logger.debug(f"update_line({tx_hash})")
        for i, line in enumerate(self._data):
            if line.tx_hash == tx_hash:
                data_index = i
                break
        else:
            logger.debug(f"update_line called for non-existent entry {tx_hash}")
            return

        line = self._data[data_index]
        logger.debug(f"update_line({data_index})")

        l = list(line)
        l[LI_HEIGHT] = height
        l[LI_CONF] = conf
        l[LI_TIMESTAMP] = timestamp
        self._data[data_index] = HistoryLine(*l)

        model = self.model().sourceModel()
        start_index = model.createIndex(data_index, 0)
        column_count = model.columnCount(start_index)
        end_index = model.createIndex(data_index, column_count-1)
        model.dataChanged.emit(start_index, end_index)

    @profiler
    def update_all(self) -> None:
        # The key reason this is used, is because the balance is dependent on the consecutive
        # transactions, so we may as well regenerate the entire data.
        model = self.model().sourceModel()
        model.beginResetModel()
        self._data = self._create_data_snapshot()
        model.set_data(self._data)
        model.endResetModel()

        # model = self.model().sourceModel()
        # start_index = model.createIndex(0, 0)
        # old_column_count = model.columnCount(start_index)
        # old_row_count = model.rowCount(start_index)
        # model.set_data(self._data)
        # new_column_count = model.columnCount(start_index)
        # new_row_count = model.rowCount(start_index)
        # end_index = model.createIndex(max(old_row_count, new_row_count)-1,
        #     max(old_column_count, new_column_count)-1)
        # model.dataChanged.emit(start_index, end_index)

        logger.debug(f"update_all()")

    def on_base_unit_changed(self) -> None:
        model = self.model().sourceModel()
        start_index = model.createIndex(0, 0)
        column_count = model.columnCount(start_index)
        row_count = model.rowCount(start_index)
        end_index = model.createIndex(row_count-1, column_count-1)
        model.dataChanged.emit(start_index, end_index)

    def get_domain(self) -> List[Any]:
        return self._wallet.get_addresses()

    def _create_data_snapshot(self) -> None:
        lines = []
        source_lines = self._wallet.get_history(self.get_domain())
        for tx_hash, height, conf, timestamp, value, balance in source_lines:
            status = self._get_tx_status(tx_hash, height, conf, timestamp)
            line = HistoryLine(tx_hash, height, conf, timestamp, value, balance, status)
            lines.append(line)
        return lines

    def _set_fiat_columns_enabled(self, flag: bool) -> None:
        self._fiat_history_enabled = flag

        if flag:
            fx = app_state.fx
            self.model().set_column_name(FIAT_AMOUNT_COLUMN, '%s '%fx.ccy + _('Amount'))
            self.model().set_column_name(FIAT_BALANCE_COLUMN, '%s '%fx.ccy + _('Balance'))

        self.setColumnHidden(FIAT_AMOUNT_COLUMN, not flag)
        self.setColumnHidden(FIAT_BALANCE_COLUMN, not flag)

    def _event_double_clicked(self, model_index: QModelIndex) -> None:
        base_index = get_source_index(model_index, HistoryItemModel)
        column = base_index.column()
        if column == DESCRIPTION_COLUMN:
            self.edit(model_index)
        else:
            line = self._data[base_index.row()]
            tx = self._wallet.get_transaction(line.tx_hash)
            self._main_window.show_transaction(tx)

    def _event_create_menu(self, position):
        selected_indexes = self.selectedIndexes()
        if not len(selected_indexes):
            return
        # This is an index on the sort/filter model, translate it to the base model.
        base_index = get_source_index(selected_indexes[0], HistoryItemModel)
        transformed_index = selected_indexes[0]

        row = base_index.row()
        column = base_index.column()
        line = self._data[row]
        # Does this even happen?
        if not line.tx_hash:
            return

        if column == 0:
            column_title = "ID"
            column_data = line.tx_hash
        else:
            column_title = COLUMN_NAMES[column]
            column_data = self.model().data(transformed_index, Qt.DisplayRole).strip()

        tx_URL = web.BE_URL(self._main_window.config, 'tx', line.tx_hash)
        tx = self._wallet.get_transaction(line.tx_hash)
        if not tx:
            # this happens sometimes on wallet synch when first starting up.
            return
        is_unconfirmed = line.height <= 0

        menu = QMenu()
        menu.addAction(_("Copy {}").format(column_title),
            lambda: app_state.app.clipboard().setText(column_data))

        if column == DESCRIPTION_COLUMN:
            # We grab a fresh reference to the current item, as it has been deleted in a
            # reported issue.
            menu.addAction(_("Edit {}").format(column_title), partial(self.edit, transformed_index))
        label = self._wallet.get_label(line.tx_hash) or None
        menu.addAction(_("Details"), lambda: self._main_window.show_transaction(tx, label))

        if is_unconfirmed and tx:
            child_tx = self._wallet.cpfp(tx, 0)
            if child_tx:
                menu.addAction(_("Child pays for parent"),
                    partial(self._main_window.cpfp, tx, child_tx))

        pr_key = self._wallet.invoices.paid.get(line.tx_hash)
        if pr_key:
            menu.addAction(read_QIcon("seal"), _("View invoice"),
                partial(self._main_window.show_invoice, pr_key))
        if tx_URL:
            menu.addAction(_("View on block explorer"), lambda: webbrowser.open(tx_URL))
        menu.exec_(self.viewport().mapToGlobal(position))

    def _get_tx_status(self, tx_hash, height, conf, timestamp):
        if conf == 0:
            tx = self._wallet.get_transaction(tx_hash)
            if not tx:
                return 3
            if height < 0:
                status = 0
            elif height == 0:
                status = 1
            else:
                status = 2
        else:
            status = 3 + min(conf, 6)
        return status

    def _format_tx_status(self, status: int, timestamp: int) -> str:
        if status < len(TX_STATUS):
            status_str = TX_STATUS[status]
        else:
            status_str = format_time(timestamp, _("unknown")) if timestamp else _("unknown")
        return status_str
