"""
This module represents a device.

Computer Systems Architecture Course
Assignment 1
March 2016
"""

from threading import Event, Thread, Semaphore
from Queue import Queue, Empty

from utils import ReusableBarrierCond


class Device(object):
    """
    Class that represents a device.
    """

    def __init__(self, device_id, sensor_data, supervisor):
        """
        Constructor.

        @type device_id: Integer
        @param device_id: the unique id of this node; between 0 and N-1

        @type sensor_data: List of (Integer, Float)
        @param sensor_data: a list containing (location, data) as measured by this device

        @type supervisor: Supervisor
        @param supervisor: the testing infrastructure's control and validation component
        """
        self.device_id = device_id
        self.sensor_data = sensor_data
        self.supervisor = supervisor
        self.script_received = Event()
        self.scripts = []
        self.timepoint_done = Event()
        self.scripts_mutex = Semaphore(1)
        self.data_mutex = Semaphore(1)
        self.thread = DeviceThread(self)
        self.tp_barrier_ready = Event()
        self.shutdown_initiated = Event()

        self.timepoint_barrier = None;
        self.script_queue = Queue()

        self.workers = [ DeviceWorker(self) for i in range(8) ]
        # print "Device %d finished __init__" % device_id

    def __str__(self):
        """
        Pretty prints this device.

        @rtype: String
        @return: a string containing the id of this device
        """
        return "Device %d" % self.device_id

    def setup_devices(self, devices):
        """
        Setup the devices before simulation begins.

        @type devices: List of Device
        @param devices: list containing all devices
        """

        if self.device_id == 0:
            self.timepoint_barrier = ReusableBarrierCond(len (devices))
            self.tp_barrier_ready.set()
        else:
            for device in devices:
                if device.device_id == 0:
                    device.tp_barrier_ready.wait()
                    self.timepoint_barrier = device.timepoint_barrier

        self.thread.start()
        for worker in self.workers:
            worker.start()

        # print "Device %d finished setup" % self.device_id


    def assign_script(self, script, location):
        """
        Provide a script for the device to execute.

        @type script: Script
        @param script: the script to execute from now on at each timepoint; None if the
            current timepoint has ended

        @type location: Integer
        @param location: the location for which the script is interested in
        """
        if script is not None:
            self.scripts_mutex.acquire()
            self.scripts.append((script, location))
            self.scripts_mutex.release()
            self.script_queue.put((script, location))
            #self.script_received.set()
        #else:
        #    self.timepoint_done.set()

    def get_data(self, location):
        """
        Returns the pollution value this device has for the given location.

        @type location: Integer
        @param location: a location for which obtain the data

        @rtype: Float
        @return: the pollution value
        """
        self.data_mutex.acquire()
        ret = self.sensor_data[location] if location in self.sensor_data else None
        self.data_mutex.release()
        return ret

    def set_data(self, location, data):
        """
        Sets the pollution value stored by this device for the given location.

        @type location: Integer
        @param location: a location for which to set the data

        @type data: Float
        @param data: the pollution value
        """
        self.data_mutex.acquire()
        if location in self.sensor_data:
            self.sensor_data[location] = data
        self.data_mutex.release()

    def shutdown(self):
        """
        Instructs the device to shutdown (terminate all threads). This method
        is invoked by the tester. This method must block until all the threads
        started by this device terminate.
        """
        self.thread.join()


class DeviceThread(Thread):
    """
    Class that implements the device's worker thread.
    """

    def __init__(self, device):
        """
        Constructor.

        @type device: Device
        @param device: the device which owns this thread
        """
        Thread.__init__(self, name="Device Thread %d" % device.device_id)
        self.device = device

    def run(self):
        # hope there is only one timepoint, as multiple iterations of the loop are not supported

        while True:
            # get the current neighbourhood
            neighbours = self.device.supervisor.get_neighbours()
            if neighbours is None:
                # print "something happened with %d" % self.device.device_id
                break

            self.device.scripts_mutex.acquire()
            for (script, location) in self.device.scripts:
                self.device.script_queue.put((script, location))
            self.device.scripts_mutex.release()

            for worker in self.device.workers:
                worker.neighbours = neighbours
                worker.timepoint_done.clear()
                worker.ready_to_start.set()

            self.device.script_queue.join()

            for worker in self.device.workers:
                worker.ready_to_start.clear()
                worker.timepoint_done.set()

            self.device.timepoint_barrier.wait()

        self.device.shutdown_initiated.set()
        for worker in self.device.workers:
            worker.ready_to_start.set()
            worker.timepoint_done.set()
            worker.join()


class DeviceWorker(Thread):
    """
    Worker class for running scripts on a device
    """

    def __init__(self, device):
        Thread.__init__(self, name="Device Worker for Device %d" % device.device_id)
        self.device = device
        self.ready_to_start = Event()
        self.neighbours = []
        self.script_queue = device.script_queue
        self.timepoint_done = Event()


    def run(self):

        while True:
            self.ready_to_start.wait()

            if self.device.shutdown_initiated.is_set():
                break

            while not (self.timepoint_done.is_set() and self.script_queue.empty()):
                try:
                    (script, location) = self.script_queue.get(block=False)
                    script_data = []

                    for device in self.neighbours:
                        data = device.get_data(location)
                        if data is not None:
                            script_data.append(data)

                    data = self.device.get_data(location)
                    if data is not None:
                        script_data.append(data)

                    if script_data != []:
                        result = script.run(script_data)

                        for device in self.neighbours:
                            device.set_data(location, result)

                        self.device.set_data(location, result)

                    self.script_queue.task_done()
                except Empty:
                    continue
