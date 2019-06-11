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
from typing import Any, List, Dict, Union, Optional
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


class HistoryLine(namedtuple("HistoryLine", "tx_hash, height, timestamp, value, position")):
    pass


LI_HASH = 0
LI_HEIGHT = 1
LI_TIMESTAMP = 2
LI_VALUE = 3
LI_POSITION = 4


class HistoryItemModel(QAbstractItemModel):
    def __init__(self, parent: Any, column_names: List[str]) -> None:
        super().__init__(parent)

        self._view = parent
        self._column_names = column_names
        self._balances = None

        self._monospace_font = QFont(platform.monospace_font)
        self._withdrawal_brush = QBrush(QColor("#BC1E1E"))
        self._invoice_icon = read_QIcon("seal")

    def set_column_names(self, column_names: List[str]) -> None:
        self._column_names = column_names[:]

    def set_column_name(self, column_index: int, column_name: str) -> None:
        self._column_names[column_index] = column_name

    def set_data(self, height: int, balance: int, data: List[HistoryLine]) -> None:
        self._height = height
        self._balance = balance
        self._data = data
        self._reset_balances()
        self._calculate_balances()

    # def set_balance(self, balance: int) -> None:
    #     self._balance = balance

    def set_height(self, height: int) -> None:
        self._height = height

    def _reset_balances(self) -> None:
        self._balances = [0] * len(self._data)

    def _calculate_balances(self, from_row: int=0) -> None:
        if not len(self._data):
            return

        # Recalculate balances as needed.
        if from_row == 0:
            balance = 0
            for i, line in enumerate(self._data):
                balance += line.value
                self._balances[i] = balance
        else:
            balance = self._balances[from_row-1]
            for i in range(from_row, len(self._data)):
                balance += self._data[i].value
                self._balances[i] = balance

        if sum(line.value for line in self._data) != self._balances[-1]:
            raise Exception("Invalid balance detected", from_row)

    # def _get_row_balance(self, row: int) -> int:
    #     line = self._data[row]
    #     conf = self._view._get_conf(line.timestamp, line.height)

    def _get_sort_key(self, line: HistoryLine) -> int:
        # ...
        if line.timestamp:
            return line.height, line.position
        elif line.height:
            return (line.height, 0) if line.height > 0 else ((1e9 - line.height), 0)
        else:
            return (1e9+1, 0)

    def _get_row(self, tx_hash: str) -> Optional[int]:
        # Get the offset of the line with the given transaction hash.
        for i, line in enumerate(self._data):
            if line.tx_hash == tx_hash:
                return i
        return None

    def _get_match_row(self, line: HistoryLine) -> int:
        # Get the existing line that precedes where the given line would go.
        new_key = self._get_sort_key(line)
        for i in range(len(self._data)-1, -1, -1):
            key = self._get_sort_key(self._data[i])
            if new_key >= key:
                return i
        return -1

    def _add_line(self, line: HistoryLine) -> int:
        match_row = self._get_match_row(line)
        insert_row = match_row + 1

        # Signal the insertion of the new row.
        self.beginInsertRows(QModelIndex(), insert_row, insert_row)
        # self._balance += line.value
        row_count = self.rowCount(QModelIndex())
        if insert_row == row_count:
            self._data.append(line)
            balance = self._balances[-1] if len(self._balances) else 0
            self._balances.append(balance)
        else:
            # Insert the data entries.
            self._data.insert(insert_row, line)
            self._balances.insert(insert_row, 0)
        self.endInsertRows()

        return insert_row

    def _remove_line(self, row: int) -> HistoryLine:
        line = self._data[row]

        self.beginRemoveRows(QModelIndex(), row, row)
        del self._data[row]
        del self._balances[row]
        self.endRemoveRows()

        return line

    def add_line(self, line: HistoryLine) -> None:
        insert_row = self._add_line(line)

        self._calculate_balances(insert_row)

        # Signal the update of the affected balances.
        start_index = self.createIndex(insert_row, BALANCE_COLUMN)
        row_count = self.rowCount(start_index)
        end_index = self.createIndex(row_count-1, BALANCE_COLUMN)
        self.dataChanged.emit(start_index, end_index)

    def update_line(self, tx_hash: str, values: Dict[int, Any]) -> bool:
        row = self._get_row(tx_hash)
        if row is None:
            logger.debug(f"update_line called for non-existent entry {tx_hash}")
            return False

        logger.debug(f"update_line tx={tx_hash} idx={row}")

        old_line = self._data[row]
        new_line = None
        if len(values):
            l = list(old_line)
            for value_index, value in values.items():
                l[value_index] = value
            new_line = self._data[row] = HistoryLine(*l)

            old_key = self._get_sort_key(old_line)
            new_key = self._get_sort_key(new_line)

            if old_key != new_key:
                # We need to move the line, so it is more than a simple row update.
                self._remove_line(row)
                insert_row = self._add_line(new_line)
                self._calculate_balances(min(insert_row, row))
                return True

        start_index = self.createIndex(row, 0)
        column_count = self.columnCount(start_index)
        end_index = self.createIndex(row, column_count-1)
        self.dataChanged.emit(start_index, end_index)

        return True

    # Overridden methods:

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
            conf = self._view._get_conf(line.timestamp, line.height)
            status = self._view._get_tx_status(
                line.tx_hash, line.height, conf, line.timestamp)
            balance = self._balances[row]

            # First check the custom sort role.
            if role == QT_SORT_ROLE:
                # Sort based on raw value.
                if column == STATUS_COLUMN:
                    return self._get_sort_key(line)
                elif column == AMOUNT_COLUMN:
                    return line.value
                elif column == BALANCE_COLUMN:
                    return balance
                elif column == FIAT_AMOUNT_COLUMN:
                    return line.value
                elif column == FIAT_BALANCE_COLUMN:
                    return balance

                # Just use the displayed text.
                role = Qt.DisplayRole
            if role == Qt.EditRole:
                if column == DESCRIPTION_COLUMN:
                    return self._view._wallet.get_label(line.tx_hash)
            elif role == Qt.DecorationRole:
                if column == ICON_COLUMN:
                    return read_QIcon(TX_ICONS[status])
                elif column == AMOUNT_COLUMN:
                    if self._view._wallet.invoices.paid.get(line.tx_hash):
                        return self._invoice_icon
            elif role == Qt.DisplayRole:
                if column == STATUS_COLUMN:
                    return self._view._format_tx_status(status, line.timestamp)
                elif column == DESCRIPTION_COLUMN:
                    return self._view._wallet.get_label(line.tx_hash)
                elif column == AMOUNT_COLUMN:
                    return self._view._main_window.format_amount(line.value,
                        True, whitespaces=True)
                elif column == BALANCE_COLUMN:
                    return self._view._main_window.format_amount(balance, whitespaces=True)
                elif column >= FIAT_AMOUNT_COLUMN:
                    fx = app_state.fx
                    fx_enabled = fx and fx.show_history()
                    if fx and fx.show_history():
                        if column == FIAT_AMOUNT_COLUMN:
                            date = timestamp_to_datetime(time.time()
                                if conf <= 0 else line.timestamp)
                            return app_state.fx.historical_value_str(line.value, date)
                        elif column == FIAT_BALANCE_COLUMN:
                            date = timestamp_to_datetime(time.time()
                                if conf <= 0 else line.timestamp)
                            return app_state.fx.historical_value_str(balance, date)
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
                suffix = "s" if conf != 1 else ""
                return f"{conf} confirmation{suffix}"

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


class HistoryView(QTableView):
    """
    Events and updating the view:
    - Blockchain events.
      - Chain event.
        - On a reorg:
        - On a new block added to the chain:
      - Missing transaction.
        - The wallet requested a missing transaction and it has arrived.
    - User events.
      - The user just edited a label.
      - Updated labels arrived from the label sync source.
    """
    def __init__(self, parent: Any, wallet: Abstract_Wallet,
            wait_for_load_event: Optional[bool]=False) -> None:
        super().__init__(parent)

        self._main_window = parent
        self._wallet = wallet

        # The data should be known, it shouldn't change underneath the view unless the view is
        # changing it. Otherwise the pinned view data will conflict with the non-pinned view
        # data.
        self._headers = COLUMN_NAMES

        self.verticalHeader().setVisible(False)
        self.setAlternatingRowColors(True)
        self.sortByColumn(STATUS_COLUMN, Qt.DescendingOrder)

        if wait_for_load_event:
            self.setEnabled(False)
            self._data = []
            self._display_height = 0
            self._balance = 0
        else:
            self._data = self._create_data_snapshot()
        model = HistoryItemModel(self, self._headers)
        model.set_data(self._display_height, self._balance, self._data)
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

        self.setVerticalScrollMode(QAbstractItemView.ScrollPerItem)
        self.setSelectionBehavior(QAbstractItemView.SelectItems)
        self.setSelectionMode(QAbstractItemView.SingleSelection)

        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self._event_create_menu)

        self._main_window.history_updated_signal.connect(self._on_history_update_event)
        self._main_window.network_chain_signal.connect(self._on_network_chain_event)
        self._main_window.new_transaction_signal.connect(self._on_new_transaction)
        app_state.app.labels_changed_signal.connect(self._on_labels_changed)

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
            end_index = model.createIndex(model.columnCount(start_index)-1, FIAT_BALANCE_COLUMN)
            model.dataChanged.emit(start_index, end_index)

    @profiler
    def _on_network_chain_event(self, old_chain, new_chain) -> None:
        logger.debug("_on_network_chain_event %s -> %s", old_chain, new_chain)
        if not old_chain:
            # At this time we ignore this event. It has not been observed to happen.
            return

        self._display_height = self._wallet.get_local_height()
        model = self.model().sourceModel()
        model.set_height(self._display_height)

        if old_chain is new_chain:
            # We detected a new block being mined.
            start_row = -1
            for i in range(len(self._data)-1, -1, -1):
                line = self._data[i]
                # NOTE: This is naive and assumes correct ordering of the underlying model data.
                # It should work, but we may want to get more specific in the case it doesn't.
                if self._display_height - line.height > 6:
                    break
                start_row = i
            logger.debug("_on_network_chain_event.start_row=%s", start_row)

            if start_row != -1:
                # For all the rows that are visually not completely confirmed (6+ confirmations).
                # Update the pending transaction statuses.
                # Update all the icons.
                start_index = model.createIndex(start_row, ICON_COLUMN)
                end_index = model.createIndex(model.rowCount(start_index)-1, STATUS_COLUMN)
                model.dataChanged.emit(start_index, end_index)
        else:
            # We detected a reorg. In theory we can do better and target the affected rows, but
            # this should be rare enough that the work can be deferred.
            self.update_all()

    @profiler
    def _on_new_transaction(self, tx: Transaction) -> None:
        tx_hash = tx.txid()
        logger.debug("_on_new_transaction %s", tx_hash)

        # If we do find it, it's going to be more recent.
        for line in reversed(self._data):
            if line.tx_hash == tx_hash:
                logger.debug("_on_new_transaction/skipped")
                return

        height, conf, timestamp = self._wallet.get_tx_height(tx_hash)
        status = self._get_tx_status(tx_hash, height, conf, timestamp)
        is_relevant, is_mine, value, fee = self._wallet.get_wallet_delta(tx)
        line = HistoryLine(tx_hash, height, timestamp, value, 0)

        model = self.model().sourceModel()
        model.add_line(line)

    @profiler
    def _on_history_update_event(self, event_name: str) -> None:
        logger.debug("_on_history_update_event %s", event_name)
        if not self.isEnabled():
            if event_name == "activate":
                self.setEnabled(True)
                self.update_all()
            else:
                logger.debug("_on_history_update_event unhandled event while loading wallet %s",
                    event_name)
            return

        if event_name == "fiat_ccy_changed":
            self.update_fx_history()
        elif event_name == "num_zeros_changed" or event_name == "base_unit_changed":
            model = self.model().sourceModel()
            start_index = model.createIndex(0, AMOUNT_COLUMN)
            end_index = model.createIndex(model.rowCount(start_index)-1, BALANCE_COLUMN)
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
            pass # self.update_all()
        elif event_name in [ "load_wallet" ]:
            # We have no use for this event at this time.
            pass
        else:
            logger.debug("_on_history_update_event unhandled event %s", event_name)

    def _on_labels_changed(self, wallet: Abstract_Wallet, updates: Any) -> None:
        logger.debug("_on_labels_changed for %d labels", len(updates))

        model = self.model().sourceModel()
        for tx_hash, label_text in updates.items():
            model.update_line(tx_hash, {})

    def update_transaction(self, tx_hash: str) -> None:
        logger.debug("update_transaction %s", tx_hash)
        height, conf, timestamp = self._wallet.get_tx_height(tx_hash)

        model = self.model().sourceModel()
        model.update_line(tx_hash, height, conf, timestamp)

    def update_line(self, tx_hash: str, height: int, conf: int, timestamp: int) -> None:
        logger.debug("update_line %s", tx_hash)
        values = {}
        values[LI_HEIGHT] = height
        values[LI_TIMESTAMP] = timestamp

        model = self.model().sourceModel()
        model.update_line(tx_hash, values)

    @profiler
    def update_all(self) -> None:
        logger.debug("update_all")

        # The key reason this is used, is because the balance is dependent on the consecutive
        # transactions, so we may as well regenerate the entire data.
        model = self.model().sourceModel()
        model.beginResetModel()
        self._data = self._create_data_snapshot()
        model.set_data(self._display_height, self._balance, self._data)
        model.endResetModel()

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
        self._balance = sum(self._wallet.get_balance(self.get_domain()))
        self._display_height = self._wallet.get_local_height()
        logger.debug("_create_data_snapshot %d", self._display_height)

        lines = []
        source_lines = self._wallet.get_history(self.get_domain())
        for tx_hash, height, conf, timestamp, value, balance in source_lines:
            lines.append(HistoryLine(tx_hash, height, timestamp, value, 0))
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
            tx = self._wallet.has_received_transaction(tx_hash)
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
            return TX_STATUS[status]
        return format_time(timestamp, _("Unknown")) if timestamp else _("Unknown")

    def _get_conf(self, timestamp: Union[bool, int], height: int) -> int:
        if timestamp:
            return max(self._display_height - height + 1, 0)
        return 0

