import fwrench.utils as utils
import numpy as np
from fwrench.datasets import MNISTDataset
from wrench.dataset import load_dataset
from wrench.endmodel import EndClassifierModel


def get_mnist(
    n_labeled_points, dataset_home, data_dir="MNIST_3000",
):

    train_data = MNISTDataset("train", name="MNIST")
    valid_data = MNISTDataset("valid", name="MNIST")
    test_data = MNISTDataset("test", name="MNIST")
    n_classes = 10

    data = data_dir
    train_data, valid_data, test_data = load_dataset(
        dataset_home, data, extract_feature=True, dataset_type="NumericDataset"
    )

    # Create subset of labeled dataset
    valid_data = valid_data.create_subset(np.arange(n_labeled_points))

    # TODO also hacky...
    # normalize MNIST data because it comes unnormalized apparently...
    train_data = utils.normalize01(train_data)
    valid_data = utils.normalize01(valid_data)
    test_data = utils.normalize01(test_data)

    # Create end model
    model = EndClassifierModel(
        batch_size=256,
        test_batch_size=512,
        n_steps=1_000,
        backbone="LENET",
        optimizer="SGD",
        optimizer_lr=1e-1,
        optimizer_weight_decay=0.0,
        binary_mode=False,
    )

    return train_data, valid_data, test_data, n_classes, model