# HTLL-IR-framework
High throughput Low Latency Information Retrieval Framework

## UV Guide for beginners
### Downloading UV
```
curl -LsSf https://astral.sh/uv/install.sh | sh
```
Adding to PATH
```
echo 'export PATH="$HOME/.uv/bin:$PATH"' >> ~/.bashrc
source ~/.bashrc

or 

echo 'export PATH="$HOME/.uv/bin:$PATH"' >> ~/.zshrc
source ~/.zshrc
```

### Verifying UV installation
```
uv --version
```

### Initializing UV project
```
uv init 
```

### To install dependencies
```
uv add numpy pandas 
```

### To install from requirements.txt ( Not needed if dependencies are already added in uv.lock )
```
uv add -r requirements.txt
uv sync
```

### To run the python file
```
uv run python main.py
```

### How to install/pin the python version
```
uv python install 3.12
uv python pin 3.12
```

## How to sync from existing environment
```
uv sync 
```

## UV Guide for beginners