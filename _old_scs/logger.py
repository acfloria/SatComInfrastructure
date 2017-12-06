import cPickle as pickle
from datetime import datetime

class Logger:
    def __init__(self):
        pass

    def logMsg(self, msg):
        now = datetime.now().strftime('%Y-%m-%d-%H-%M-%S')
        file = open(now, 'w')
        pickle.dump(msg, file)
        file.close()
