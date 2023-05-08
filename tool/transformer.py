import torch
from torch.utils.data import DataLoader, Dataset
from transformers import DistilBertTokenizer, DistilBertForSequenceClassification, AdamW
from typing import Any, List
import os

class QAData(Dataset):
    def __init__(self, data, tokenizer, max_length=32):
        self.data = data
        self.tokenizer = tokenizer
        self.max_length = max_length

    def __len__(self):
        return len(self.data)

    def __getitem__(self, idx):
        item = self.data[idx]
        encoding = self.tokenizer(item['q'], truncation=True, padding='max_length', max_length=self.max_length, return_tensors="pt")
        return {
            'input_ids': encoding['input_ids'].flatten(),
            'attention_mask': encoding['attention_mask'].flatten(),
            'labels': torch.tensor(item['label'], dtype=torch.long)
        }

def train(model, train_data, epochs, batch_size, device):
    tokenizer = DistilBertTokenizer.from_pretrained("distilbert-base-uncased")
    dataset = QAData(train_data, tokenizer)
    dataloader = DataLoader(dataset, batch_size=batch_size)

    optimizer = AdamW(model.parameters(), lr=5e-5)

    model.train()
    model.to(device)

    for epoch in range(epochs):
        for batch in dataloader:
            input_ids = batch['input_ids'].to(device)
            attention_mask = batch['attention_mask'].to(device)
            labels = batch['labels'].to(device)

            optimizer.zero_grad()

            outputs = model(input_ids, attention_mask=attention_mask, labels=labels)
            loss = outputs.loss
            loss.backward()

            optimizer.step()

def export_model(model, file_path):
    torch.save(model.state_dict(), file_path)

def load_model(file_path):
    model = DistilBertForSequenceClassification.from_pretrained("distilbert-base-uncased")
    model.load_state_dict(torch.load(file_path))
    return model

def predict(model, query, train_data, tokenizer, device, top_k=3):
    model.eval()
    model.to(device)

    inputs = tokenizer(query, truncation=True, padding='max_length', max_length=32, return_tensors="pt")
    input_ids = inputs['input_ids'].to(device)
    attention_mask = inputs['attention_mask'].to(device)

    with torch.no_grad():
        logits = model(input_ids, attention_mask=attention_mask).logits

    probs = torch.softmax(logits, dim=-1)
    top_probs, top_labels = torch.topk(probs, top_k, dim=-1)

    result = []
    for i in range(top_k):
        result.append({
            'q': train_data[top_labels[0, i]]['q'],
            'a': train_data[top_labels[0, i]]['a'],
            'prob': top_probs[0, i].item()
        })

    return result

class Transformers:
    name: str = 'transformers'
    model: Any
    device: Any
    tokenizer: Any
    input_data: List[dict]
    enable: bool = False
    depth: int = 20
    
    def __init__(self):     
        self.tokenizer = DistilBertTokenizer.from_pretrained("distilbert-base-uncased")
        self.device = torch.device("cuda:0" if torch.cuda.is_available() else "cpu")

    def save_model(self, model_file: str) -> bool:
        if not self.enable:
            return False

        tmp_file = model_file + '.bak'
        ret = export_model(self.model, tmp_file)
        if not ret:
            return False

        return os.rename(tmp_file, model_file)

    def load_model(self, model_file: str):
        self.model = load_model(model_file)
        self.enable = True
        return self.model

    def predict(self, query, predict_limit: int = 3):
        if not self.enable:
            return {}
        # limit over flow
        if predict_limit >= len(self.input_data):
            predict_limit = self.input_data - 1

        return predict(self.model, query, self.input_data, self.tokenizer, self.device, top_k=predict_limit)
        
    def train(self, input_data, depth):
        import random
        from tool.util import log_dbg

        self.depth = depth

        self.input_data = []
        #[x for x in input_data if x is not None]

        label = 0
        while True:
            iter = random.choice(input_data)
            if not iter:
                continue
            if len(self.input_data) > self.depth:
                break
            iter['label'] = label
            self.input_data.insert(0, iter)
            label += 1
            log_dbg('ran ' + str(iter))

        
        self.model = DistilBertForSequenceClassification.from_pretrained("distilbert-base-uncased", num_labels=len(input_data))
        ret = train(self.model, self.input_data, epochs=5, batch_size=2, device=self.device)

        self.enable = True

        return ret

def transformers_predict(input_data):
    import json

    print('input: ' + str(input_data))
    
    trans = Transformers()
    trans.train(input_data)

    # 示例1
    query = "摸头"
    print(query)
    predictions = trans.predict(query)
    print(json.dumps(predictions, indent=2, ensure_ascii=False))

    # 示例1
    query = "摸摸耳朵"
    print(query)
    predictions = trans.predict(query)
    print(json.dumps(predictions, indent=2, ensure_ascii=False))
    

def test_predict(input_data):
    import json

    model = DistilBertForSequenceClassification.from_pretrained("distilbert-base-uncased", num_labels=len(input_data))
    tokenizer = DistilBertTokenizer.from_pretrained("distilbert-base-uncased")

    device = torch.device("cuda:0" if torch.cuda.is_available() else "cpu")
    train(model, input_data, epochs=5, batch_size=2, device=device)
    #export_model(model, "trained_model.pt")

    loaded_model = model #load_model("trained_model.pt")

    # 示例1
    query = "摸头"
    print(query)
    predictions = predict(loaded_model, query, input_data, tokenizer, device, top_k=4)
    print(json.dumps(predictions, indent=2, ensure_ascii=False))
    
    # 示例2
    query = "摸摸耳朵"
    print(query)
    predictions = predict(loaded_model, query, input_data, tokenizer, device)
    print(json.dumps(predictions, indent=2, ensure_ascii=False))

'''
# pip install transformers

if __name__ == "__main__": 
    # 输入数据
    input_data =  [
        {'q': '摸摸头', 'label': 0, 'a': '好的，请摸头'},
        {'q': '我摸过你头吗?', 'a': '当然了.可以摸头', 'label': 2},
        {'q': '我想摸摸头', 'a': 'Master请摸摸头', 'label': 1},
        {'q': '摸摸耳朵', 'a': '请摸耳朵', 'label': 3},
        {'q': '我摸摸耳朵', 'a': '摸摸耳朵真好', 'label': 4},
        {'q': '我能摸摸你耳朵吗?', 'a': '随时可以摸耳朵', 'label': 5},
        None,
        None
    ]

    #test_predict(input_data)
    
    transformers_predict(input_data)
'''
