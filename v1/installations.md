# Installing celery
1. Ref0: [Neuralnine Github Example](https://github.com/NeuralNine/youtube-tutorials/tree/main/Task%20Queues)
2. Ref1: [With Server](https://medium.com/dev-whisper/getting-started-with-celery-a-comprehensive-guide-9b3a65db3de4)

```bash
uv add celery
```

# Installing rabbitmq server
1. Rabbitmq Docs Part1: [Guide 1](https://www.cloudamqp.com/blog/part1-rabbitmq-for-beginners-what-is-rabbitmq.html)
2. Rabbitmq Docs Part2: [Guide 2](https://www.cloudamqp.com/blog/part2-3-rabbitmq-for-beginners_example-and-sample-code-python.html)
## 1. Mac
```bash
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
brew install rabbitmq
```
Optionally add this into profile ( if required )
`PATH=$PATH:/usr/local/sbin`

Configuring the system host name
Use the scutil command to permanently set your host name:

```bash
sudo scutil --set HostName myhost.local
```

Add `myhost myhost.local` to the `/etc/host/`
```bash
127.0.0.1       localhost myhost myhost.local
```

Start/Stop rabbit-mq server

```bash
sudo rabbitmq-server
sudo rabbitmqctl status
sudo rabbitmq-server -detached
sudo rabbitmqctl stop
```
## 2. Docker Compose 
Ref: [Medium Link](https://medium.com/@kaloyanmanev/how-to-run-rabbitmq-in-docker-compose-e5baccc3e644)

Follow this Dokcer Compose File:
```bash
services:
  rabbitmq:
    image: rabbitmq:3-management
    container_name: rabbitmq
    restart: always
    ports:
      - 5672:5672
      - 15672:15672
    environment:
      RABBITMQ_DEFAULT_USER: admin
      RABBITMQ_DEFAULT_PASS: admin
    configs:
      - source: rabbitmq-plugins
        target: /etc/rabbitmq/enabled_plugins
    volumes:
      - rabbitmq-lib:/var/lib/rabbitmq/
      - rabbitmq-log:/var/log/rabbitmq

configs:
  rabbitmq-plugins:
    content: "[rabbitmq_management]."  

volumes:
  rabbitmq-lib:
    driver: local
  rabbitmq-log:
    driver: local
```

## 3. Linux


--
The rabbitmq localhost montioring: [http://localhost:15672](http://localhost:15672)


