from typing import Any, Dict, List, Optional, Tuple, Union, Callable
import logging
import numpy as np
from tqdm import tqdm, trange

import torch
import torch.nn.functional as F
from torch import optim
from torch.utils.data import DataLoader

from transformers import get_linear_schedule_with_warmup

from ..basemodel import BaseTorchModel, BaseModel
from ..dataset import BaseDataset, TorchDataset
from ..backbone import MLP
from ..utils import cross_entropy_with_probs

logger = logging.getLogger(__name__)


class MLPModel(BaseTorchModel):
    def __init__(self,
                 lr: Optional[float] = 1e-3,
                 l2: Optional[float] = 1e-3,
                 hidden_size: Optional[int] = 100,
                 dropout: Optional[float] = 0.0,
                 batch_size: Optional[int] = 32,
                 test_batch_size: Optional[int] = 512,
                 n_steps: Optional[int] = 100,
                 binary_mode: Optional[bool] = False
                 ):
        super().__init__()
        self.hyperparas = {
            'lr': lr,
            'l2': l2,
            'batch_size': batch_size,
            'test_batch_size': test_batch_size,
            'hidden_size': hidden_size,
            'dropout': dropout,
            'n_steps': n_steps,
            'binary_mode': binary_mode,
        }
        self.model: Optional[BaseModel] = None

    def fit(self,
            dataset_train: Union[BaseDataset, np.ndarray],
            y_train: Optional[np.ndarray] = None,
            dataset_valid: Optional[Union[BaseDataset, np.ndarray]] = None,
            y_valid: Optional[np.ndarray] = None,
            sample_weight: Optional[np.ndarray] = None,
            evaluation_step: Optional[int] = 100,
            metric: Optional[Union[str, Callable]] = 'acc',
            direction: Optional[str] = 'auto',
            patience: Optional[int] = 20,
            tolerance: Optional[float] = -1.0,
            device: Optional[torch.device] = None,
            verbose: Optional[bool] = True,
            **kwargs: Any):

        if not verbose:
            logger.setLevel(logging.ERROR)

        self._update_hyperparas(**kwargs)
        hyperparas = self.hyperparas

        n_steps = hyperparas['n_steps']
        train_dataloader = DataLoader(TorchDataset(dataset_train, n_data=n_steps * hyperparas['batch_size']),
                                      batch_size=hyperparas['batch_size'], shuffle=True)

        if y_train is not None:
            y_train = torch.Tensor(y_train).to(device)

        if sample_weight is None:
            sample_weight = np.ones(len(dataset_train))
        sample_weight = torch.FloatTensor(sample_weight).to(device)

        n_class = len(dataset_train.id2label)
        input_size = dataset_train.features.shape[1]
        model = MLP(
            input_size=input_size,
            n_class=n_class,
            hidden_size=hyperparas['hidden_size'],
            dropout=hyperparas['dropout'],
            binary_mode=hyperparas['binary_mode'],
        ).to(device)
        self.model = model

        optimizer = optim.Adam(model.parameters(), lr=hyperparas['lr'], weight_decay=hyperparas['l2'])

        # Set up the learning rate scheduler
        scheduler = get_linear_schedule_with_warmup(optimizer, num_warmup_steps=0, num_training_steps=n_steps)

        valid_flag = self._init_valid_step(dataset_valid, y_valid, metric, direction, patience, tolerance)

        history = {}
        last_step_log = {'loss': -1}
        try:
            with trange(n_steps, desc="training:", unit="steps", disable=not verbose, position=0, ncols=200,
                        leave=True) as pbar:
                model.train()
                step = 0
                for batch in train_dataloader:
                    step += 1
                    optimizer.zero_grad()
                    outputs = model(batch)
                    batch_idx = batch['ids'].to(device)
                    if y_train is not None:
                        target = y_train[batch_idx]
                    else:
                        target = batch['labels'].to(device)
                    loss = cross_entropy_with_probs(outputs, target, reduction='none')
                    batch_sample_weights = sample_weight[batch_idx]
                    loss = torch.mean(loss * batch_sample_weights)
                    loss.backward()
                    optimizer.step()
                    scheduler.step()

                    if valid_flag and step % evaluation_step == 0:
                        metric_value, early_stop_flag, info = self._valid_step(step)
                        if early_stop_flag:
                            logger.info(info)
                            break

                        history[step] = {
                            'loss': loss.item(),
                            f'val_{metric}': metric_value,
                            f'best_val_{metric}': self.best_metric_value,
                            f'best_step': self.best_step,
                        }
                        last_step_log.update(history[step])

                    last_step_log['loss'] = loss.item()
                    pbar.update()
                    pbar.set_postfix(ordered_dict=last_step_log)
        except KeyboardInterrupt:
            logger.info(f'KeyboardInterrupt! do not terminate the process in case need to save the best model')

        self._finalize()

        return history