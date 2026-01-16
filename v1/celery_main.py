from celery import Celery

app = Celery('hellocelery', 
            broker='amqp://admin:admin@localhost:5672//'
            )

@app.task
def hello():
    return 'hello world, from celery'