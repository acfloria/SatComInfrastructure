# fw_SatCom
Iridium SBD Satellite Communication System utility software for data relay and handling.

The system is based on the [Rock7 RockBLOCK](http://www.rock7mobile.com/products-rockblock) Iridium modem.

Runs on Ubuntu. Not tested on Windows.

## Architecture

The Iridium SBD message relay software consists of the following modules:

* `rabbitmq` - Message broker running on the relay server, taking care of queueing and distributing the messages to other components ([link](https://www.rabbitmq.com/))
* `relay.py` - Python script running on the relay server providing the Rock7 HTTP POST and rabbitmq interfaces.
* `udp2rabbit.py` - Python script running on the ground station computer together with QGC. Connects to the rabbitmq broker running on the relay server and retransmits the messages from/to QGC using a local UDP socket.
* `simulator.py` - Python script used for development and testing of the relay system. Replaces the actual Iridium hardware by simulating the Iridium 9602 modem UART interface and the Rock7 HTTP POST interface.

![Architecture](architecture.png)

Full system architecture.

![Architecture with simulator](architecture_sim.png)

System architecture showing the use of the Iridium System simulator.

## Setup
### Relay server setup

* The server working as a message relay should have a static IP address and two publicly accessible, open TCP ports:

	* `5672` for the RabbitMQ message broker (can be changed in the rabbitmq settings)
	* `45679` for the HTTP POST interface (can be changed in the `.cfg` files)

* Install the required python modules

    `sudo pip install pika`
    `sudo pip install tornado`
    `sudo pip install future`

* Install `rabbitmq` message broker

    `sudo apt install rabbitmq-server`

* Configure the broker's credentials (change PWD to your preferred password):

    `sudo rabbitmqctl add_user iridiumsbd PWD`
    `sudo rabbitmqctl set_permissions iridiumsbd ".*" ".*" ".*"`

* Configure the broker's queues:

    `./setup_rabbit.py localhost iridiumsbd PWD`

* Verify the setup:

    `sudo rabbitmqctl list_queues`

    This should give you a list of 4 queues: `MO`, `MO_LOG`, `MT`, `MT_LOG`

* Edit the `relay.cfg` configuration file to reflect your settings.

* Visit the [Rock7 RockBLOCK configuration site](https://rockblock.rock7.com/Operations) and set up the `Delivery Groups` to deliver messages to the relay server's IP (it should be given in the format `http://IP:port`).

### QGC computer setup

* Install the required python modules

    `sudo pip install pika`
    `sudo pip install tornado`
    `sudo pip install future`

* Edit the `udp2rabbit.cfg` configuration file to reflect your settings.

* Add a UDP connection in QGC with the parameters:

    * `Listening port: 10000`
    * `Target hosts: 127.0.0.1:10001`

## Using the system

### Relay server

Start the `relay.py` script. This has to be running whenever satellite communication is used. To prevent the process from getting killed it's advised to run it using the `screen` tool. relay.py is started automatically now, to check it use 'screen -r'. leave screen with ctrl-A -> d to detatch from screen (dont stop or kill it).

relay.py is started in /etc/rc.local.



### QGC computer

Open the local UDP connection in QGC.

Start the `udp2rabbit.py` script. This has to be running together with QGC to send the messages to/from the relay server.

### Simulator

The simulator replaces the actual Iridium System hardware (modem, satellites and iridium gateway)

## TODOs

* Write a logging app making use of the `MO_LOG` and `MT_LOG` queues.
* Integrate the RabbitMQ interface into QGC, eliminating the need of the `udp2rabbit.py` script.