"""
This module represents a device.

Computer Systems Architecture Course
Assignment 1
March 2017
"""

from threading import Event, Thread, Lock
from Queue import Queue

from barrier import ReusableBarrierCond


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
        self.thread = DeviceThread(self)
        self.tp_barrier_ready = Event()
        self.wait_for_scripts = Event()

        self.location_mutexes_mutex = None
        self.location_mutexes = {}

        self.timepoint_barrier = None
        self.work_queue = Queue()

        self.workers = [DeviceWorker(self) for _ in range(8)]
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
            self.timepoint_barrier = ReusableBarrierCond(len(devices))
            self.location_mutexes_mutex = Lock()
            self.tp_barrier_ready.set()
        else:
            for device in devices:
                if device.device_id == 0:
                    device.tp_barrier_ready.wait()
                    self.timepoint_barrier = device.timepoint_barrier
                    self.location_mutexes = device.location_mutexes
                    self.location_mutexes_mutex = device.location_mutexes_mutex

        self.thread.start()
        for worker in self.workers:
            worker.start()

        with self.location_mutexes_mutex:
            for location in self.sensor_data.keys():
                self.location_mutexes[location] = Lock()



    def assign_script(self, script, location):
        """
        Provide a script for the device to execute.

        @type script: Script
        @param script: the script to execute from now on at each timepoint; None if the
            current timepoint has ended

        @type location: Integer
        @param location: the location for which the script is interested in
        """
        self.wait_for_scripts.wait()
        if script is not None:
            self.scripts.append((script, location))
            self.work_queue.put((script, location))
        else:
            self.wait_for_scripts.clear()
            self.timepoint_done.set()

    def get_data(self, location):
        """
        Returns the pollution value this device has for the given location.

        @type location: Integer
        @param location: a location for which obtain the data

        @rtype: Float
        @return: the pollution value
        """
        ret = self.sensor_data[location] if location in self.sensor_data else None
        return ret

    def set_data(self, location, data):
        """
        Sets the pollution value stored by this device for the given location.

        @type location: Integer
        @param location: a location for which to set the data

        @type data: Float
        @param data: the pollution value
        """
        if location in self.sensor_data:
            self.sensor_data[location] = data

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

        while True:
            # get the current neighbourhood
            neighbours = self.device.supervisor.get_neighbours()
            if neighbours is None:
                break

            for worker in self.device.workers:
                worker.neighbours = neighbours

            for (script, location) in self.device.scripts:
                self.device.work_queue.put((script, location))

            self.device.wait_for_scripts.set()

            self.device.timepoint_done.wait()

            self.device.work_queue.join()

            self.device.timepoint_done.clear()

            self.device.timepoint_barrier.wait()

        for worker in self.device.workers:
            self.device.work_queue.put((None, None))

        for worker in self.device.workers:
            worker.join()



class DeviceWorker(Thread):
    """
    Worker class for running scripts on a device
    """

    def __init__(self, device):
        Thread.__init__(self, name="Device Worker for Device %d" % device.device_id)
        self.device = device
        self.neighbours = []


    def run(self):

        while True:
            (script, location) = self.device.work_queue.get(block=True)

            if script is None and location is None:
                self.device.work_queue.task_done()
                break

            with self.device.location_mutexes[location]:
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

            self.device.work_queue.task_done()
