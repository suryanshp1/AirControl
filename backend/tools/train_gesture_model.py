"""
AirControl — Neural Network Training Script
===========================================

Trains a lightweight MLP (Multi-Layer Perceptron) on the collected landmark data.
Outputs a Torchscript model gesture_clf.pt for production deployment.
"""

import os
import csv
import numpy as np
import torch
import torch.nn as nn
import torch.optim as optim
from torch.utils.data import Dataset, DataLoader
from sklearn.model_selection import train_test_split
from sklearn.metrics import classification_report, confusion_matrix

DATA_FILE = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'model', 'training_data.csv'))
MODEL_FILE = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'model', 'gesture_clf.pt'))

# Static gestures to learn
GESTURE_CLASSES = [
    "none", "open_palm", "fist", "pointing_up", 
    "thumb_up", "thumb_down", "victory"
]
CLASS_TO_IDX = {name: idx for idx, name in enumerate(GESTURE_CLASSES)}
NUM_CLASSES = len(GESTURE_CLASSES)
INPUT_FEATURES = 63 # 21 landmarks * 3 coordinates (x,y,z)

class GestureDataset(Dataset):
    def __init__(self, X, y):
        self.X = torch.tensor(X, dtype=torch.float32)
        self.y = torch.tensor(y, dtype=torch.long)
        
    def __len__(self):
        return len(self.X)
    
    def __getitem__(self, idx):
        return self.X[idx], self.y[idx]

class GestureMLP(nn.Module):
    def __init__(self, input_size, num_classes):
        super(GestureMLP, self).__init__()
        self.network = nn.Sequential(
            nn.Linear(input_size, 128),
            nn.BatchNorm1d(128),
            nn.ReLU(),
            nn.Dropout(0.3),
            
            nn.Linear(128, 64),
            nn.BatchNorm1d(64),
            nn.ReLU(),
            nn.Dropout(0.2),
            
            nn.Linear(64, num_classes)
        )
        
    def forward(self, x):
        return self.network(x)

def load_data(filepath):
    if not os.path.exists(filepath):
        print(f"ERROR: Dataset not found at {filepath}")
        print("Please run `python collect_training_data.py` first.")
        return None, None
        
    X, y = [], []
    with open(filepath, 'r') as f:
        reader = csv.reader(f)
        header = next(reader) # skip
        for row in reader:
            if not row: continue
            label_name = row[0].upper() # upper case to match ENUM if written that way
            label_name = label_name.lower() # ensure lowercase for mapping
            if label_name in CLASS_TO_IDX:
                X.append([float(val) for val in row[1:64]])
                y.append(CLASS_TO_IDX[label_name])
                
    return np.array(X), np.array(y)

def main():
    print("--- AirControl MLP Training ---")
    X, y = load_data(DATA_FILE)
    if X is None or len(X) == 0:
        print("No training data.")
        return
        
    print(f"Loaded {len(X)} samples.")
    
    # Train / Test split
    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42, stratify=y)
    
    train_dataset = GestureDataset(X_train, y_train)
    test_dataset = GestureDataset(X_test, y_test)
    
    train_loader = DataLoader(train_dataset, batch_size=64, shuffle=True)
    test_loader = DataLoader(test_dataset, batch_size=64, shuffle=False)
    
    # Initialize Model, Loss, Optimizer
    model = GestureMLP(INPUT_FEATURES, NUM_CLASSES)
    criterion = nn.CrossEntropyLoss(label_smoothing=0.1)
    optimizer = optim.Adam(model.parameters(), lr=0.002, weight_decay=1e-4)
    
    epochs = 40
    print(f"Training for {epochs} epochs...")
    
    for epoch in range(epochs):
        model.train()
        train_loss = 0.0
        for batch_X, batch_y in train_loader:
            optimizer.zero_grad()
            outputs = model(batch_X)
            loss = criterion(outputs, batch_y)
            loss.backward()
            optimizer.step()
            train_loss += loss.item() * batch_X.size(0)
            
        train_loss /= len(train_loader.dataset)
        
        # Validation
        model.eval()
        correct = 0
        total = 0
        with torch.no_grad():
            for batch_X, batch_y in test_loader:
                outputs = model(batch_X)
                _, predicted = torch.max(outputs.data, 1)
                total += batch_y.size(0)
                correct += (predicted == batch_y).sum().item()
                
        val_acc = 100 * correct / total
        
        if (epoch+1) % 10 == 0:
            print(f"Epoch {epoch+1:02d}/{epochs} - Loss: {train_loss:.4f} - Val Accuracy: {val_acc:.2f}%")
            
    # Final Evaluation metrics
    model.eval()
    y_pred, y_true = [], []
    with torch.no_grad():
        for batch_X, batch_y in test_loader:
            outputs = model(batch_X)
            _, predicted = torch.max(outputs.data, 1)
            y_pred.extend(predicted.numpy())
            y_true.extend(batch_y.numpy())
            
    print("\n--- Evaluation Metrics ---")
    target_names = [GESTURE_CLASSES[i] for i in sorted(list(set(y_true)))]
    print(classification_report(y_true, y_pred, target_names=target_names))
    print("Confusion Matrix:")
    print(confusion_matrix(y_true, y_pred))
    
    # Save the model
    # We save the state dict. Wait, TorchScript is better for easy loading without full class def.
    # We will trace the model with dummy input.
    dummy_input = torch.randn(1, 63)
    model.eval()
    traced_model = torch.jit.trace(model, dummy_input)
    traced_model.save(MODEL_FILE)
    print(f"\nModel saved successfully as TorchScript format: {MODEL_FILE}")

if __name__ == "__main__":
    main()
