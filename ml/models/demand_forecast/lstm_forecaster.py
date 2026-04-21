"""Compact LSTM forecaster — PyTorch sequence model.

Implements BaseForecaster for experiment scripts.

Tier 2: stop Airflow workers + Superset before running.
  docker compose stop airflow-worker airflow-scheduler superset

AMD GPU acceleration via DirectML:
  pip install torch torch-directml>=0.2
  device = torch_directml.device()

Input: flat 2D feature matrix — internally reshaped to 3D (batch, lookback, features).
Lookback window: 24 hours by default (covers same-hour-yesterday lag implicitly).
"""
from __future__ import annotations

import json

import mlflow
import numpy as np


class LSTMForecaster:
    def __init__(
        self,
        hidden_size: int = 64,
        num_layers: int = 2,
        dropout: float = 0.2,
        lookback: int = 24,
        lr: float = 1e-3,
        max_epochs: int = 50,
        batch_size: int = 512,
        patience: int = 10,
    ) -> None:
        self.hidden_size = hidden_size
        self.num_layers = num_layers
        self.dropout = dropout
        self.lookback = lookback
        self.lr = lr
        self.max_epochs = max_epochs
        self.batch_size = batch_size
        self.patience = patience
        self._model = None
        self._n_features: int | None = None

    @property
    def model_type(self) -> str:
        return "lstm"

    def fit(
        self,
        X_train: np.ndarray,
        y_train: np.ndarray,
        X_val: np.ndarray,
        y_val: np.ndarray,
    ) -> None:
        import torch
        import torch.nn as nn
        from torch.utils.data import DataLoader, TensorDataset

        device = _get_device()
        n_features = X_train.shape[1]
        self._n_features = n_features

        X_tr_seq, y_tr_seq = _make_sequences(X_train, y_train, self.lookback)
        X_val_seq, y_val_seq = _make_sequences(X_val, y_val, self.lookback)

        train_ds = TensorDataset(
            torch.tensor(X_tr_seq, dtype=torch.float32),
            torch.tensor(y_tr_seq, dtype=torch.float32),
        )
        val_ds = TensorDataset(
            torch.tensor(X_val_seq, dtype=torch.float32),
            torch.tensor(y_val_seq, dtype=torch.float32),
        )
        train_loader = DataLoader(train_ds, batch_size=self.batch_size, shuffle=False)
        val_loader = DataLoader(val_ds, batch_size=self.batch_size, shuffle=False)

        self._model = _LSTMNet(n_features, self.hidden_size, self.num_layers, self.dropout).to(device)
        optimizer = torch.optim.Adam(self._model.parameters(), lr=self.lr)
        criterion = nn.HuberLoss()

        best_val_loss = float("inf")
        patience_counter = 0
        best_state = None

        for epoch in range(self.max_epochs):
            self._model.train()
            for X_batch, y_batch in train_loader:
                X_batch, y_batch = X_batch.to(device), y_batch.to(device)
                optimizer.zero_grad()
                loss = criterion(self._model(X_batch).squeeze(), y_batch)
                loss.backward()
                optimizer.step()

            self._model.eval()
            val_loss = 0.0
            with torch.no_grad():
                for X_batch, y_batch in val_loader:
                    X_batch, y_batch = X_batch.to(device), y_batch.to(device)
                    val_loss += criterion(self._model(X_batch).squeeze(), y_batch).item()
            val_loss /= len(val_loader)

            if val_loss < best_val_loss:
                best_val_loss = val_loss
                best_state = {k: v.cpu().clone() for k, v in self._model.state_dict().items()}
                patience_counter = 0
            else:
                patience_counter += 1
                if patience_counter >= self.patience:
                    break

        if best_state is not None:
            self._model.load_state_dict(best_state)

    def predict(self, X: np.ndarray) -> np.ndarray:
        if self._model is None:
            raise RuntimeError("Call fit() before predict().")
        import torch

        device = _get_device()
        X_seq, _ = _make_sequences(X, np.zeros(len(X)), self.lookback)
        self._model.eval()
        with torch.no_grad():
            preds = self._model(
                torch.tensor(X_seq, dtype=torch.float32).to(device)
            ).squeeze().cpu().numpy()
        full_preds = np.zeros(len(X))
        full_preds[self.lookback:] = np.maximum(preds, 0.0)
        return full_preds

    def log_model(self, artifact_path: str = "model") -> None:
        if self._model is None:
            raise RuntimeError("Call fit() before log_model().")
        import torch
        import mlflow.pytorch

        params = {
            "hidden_size": self.hidden_size,
            "num_layers": self.num_layers,
            "dropout": self.dropout,
            "lookback": self.lookback,
            "lr": self.lr,
            "max_epochs": self.max_epochs,
            "batch_size": self.batch_size,
        }
        mlflow.log_param("model_type", self.model_type)
        mlflow.log_param("hyperparams", json.dumps(params))
        mlflow.log_param("device", str(_get_device()))
        mlflow.pytorch.log_model(self._model, name=artifact_path)


class _LSTMNet:
    def __new__(cls, n_features: int, hidden_size: int, num_layers: int, dropout: float):
        import torch.nn as nn

        class Net(nn.Module):
            def __init__(self):
                super().__init__()
                self.lstm = nn.LSTM(
                    input_size=n_features,
                    hidden_size=hidden_size,
                    num_layers=num_layers,
                    dropout=dropout if num_layers > 1 else 0.0,
                    batch_first=True,
                )
                self.fc = nn.Linear(hidden_size, 1)

            def forward(self, x):
                out, _ = self.lstm(x)
                return self.fc(out[:, -1, :])

        return Net()


def _make_sequences(
    X: np.ndarray, y: np.ndarray, lookback: int
) -> tuple[np.ndarray, np.ndarray]:
    n = len(X)
    if n <= lookback:
        return np.empty((0, lookback, X.shape[1])), np.empty(0)
    seqs = np.stack([X[i: i + lookback] for i in range(n - lookback)])
    targets = y[lookback:]
    return seqs, targets


def _get_device():
    try:
        import torch_directml
        return torch_directml.device()
    except ImportError:
        import torch
        return torch.device("cpu")
