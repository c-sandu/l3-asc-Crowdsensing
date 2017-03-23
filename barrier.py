"""
This module contains definition of a reusable barrier class.

Computer Systems Architecture Course
Assignment 1
March 2017
"""


from threading import Condition

class ReusableBarrierCond(object):
    """ Reusable barrier, using a Condition variable """

    def __init__(self, num_threads):
        """
        Constructor.

        @type num_threads: Integer
        @param num_threads: the number of threads that the barrier waits for
        """
        self.num_threads = num_threads
        self.count_threads = self.num_threads
        self.cond = Condition()

    def wait(self):
        """
        Wait method.

        All threads calling this will block until the num_threads-th one arrives
        and unblocks them.
        """
        self.cond.acquire()
        self.count_threads -= 1
        if self.count_threads == 0:
            self.cond.notify_all()
            self.count_threads = self.num_threads
        else:
            self.cond.wait()
        self.cond.release()
