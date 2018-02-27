#!/usr/bin/env python3
'''
measurement of rpm vs pwm and I vs pwm, using a UC4H ESC KISS32A node
=> calculation of estimated thrust vs pwm
=> fit to poly function to estimate MOT_THST_EXPO parameter

OlliW 27.Feb.2018
'''

#based on the example here: http://uavcan.org/Implementations/Pyuavcan/Examples/ESC_throttle_control/
#see https://groups.google.com/forum/#!topic/uavcan/cz7UBGZTdF8 for how to get things working on Win
# thx, Pavel !

import uavcan, time, math
import msvcrt, sys
import matplotlib.pyplot as plt
import numpy as np
from scipy.optimize import curve_fit


# class to record data in repeated up/down sweeps
class cRecord:

    def __init__(self,_node,_escIndex,_fig=None,_ax=None,_ax2=None):
        self.node = _node
        self.escIndex = _escIndex
        
        self.status = 0 #0 = init, 1 = run, 2 = stop, 3 = exit
        self.status_cnt = 20 #startup initialization time, 1 sec
        self.start_time = 0
        self.setpoint = int(0)
        self.direction_up = True
        
        if self.escIndex > 3:
            self.emptyCommands = [0]*(self.escIndex+1) #this adapts to the number of ESCs
        else:    
            self.emptyCommands = [0,0,0,0] #assume at minimum 4 ESCs
            
        self.pwm = []    
        self.rpm = []    
        self.current = []    
        self.fig = _fig
        self.ax = _ax
        self.ax2 = _ax2

    def broadcastEscSetpoint(self):
        if self.status == 0:
            self.setpoint = int(0)
            self.status_cnt -= 1
            if self.status_cnt <= 0: 
                self.start_time = time.time()
                self.status = 1
        elif self.status == 1 or self.status == 2:
            if self.direction_up:
                self.setpoint += 20 
                if self.setpoint >= 8100: self.direction_up = False
            else:
                self.setpoint -= 20
                if self.setpoint <= 100: self.direction_up = True
            if self.status == 2:
                self.direction_up = False # 'quick' abort, comment out to have complete sweeps
                if self.setpoint <= 101:
                    self.setpoint = int(0)
                    self.status = 3
    
        #print(self.setpoint)
        commands = self.emptyCommands
        commands[self.escIndex] = self.setpoint
        message = uavcan.equipment.esc.RawCommand(cmd=commands)
        self.node.broadcast(message)
    
    def printEscStatus(self,msg):
        if self.setpoint > 0:
            self.pwm.append(self.setpoint)
            self.rpm.append(msg.message.rpm)
            self.current.append(msg.message.current)
        if self.status >= 2:
            print('  ',self.setpoint,', ',msg.message.rpm,'rpm, ',msg.message.current,'A','STOP')
        else:
            print('  ',self.setpoint,', ',msg.message.rpm,'rpm, ',msg.message.current,'A')
        if self.fig:
            self.ax.clear()
            self.ax.plot(self.pwm,self.rpm,'bo')
            self.ax2.clear()
            self.ax2.plot(self.pwm,self.current,'r')
            self.fig.canvas.draw()
            time.sleep(0.01)
        
        #print(uavcan.to_yaml(msg))
        
    def plot(self):
        return

    def run(self):
        hPeriodic = self.node.periodic(0.05, self.broadcastEscSetpoint)
        hEscStatus = self.node.add_handler(uavcan.equipment.esc.Status, self.printEscStatus)
        while self.status < 3:
            try:
                self.node.spin(1)
                self.plot()
                if msvcrt.kbhit():
                    msvcrt.getch()
                    self.status = 2
            #except UAVCANException as ex: #leads to NameError: name is not defined ???
            #    print('NODE ERROR:', ex)            
            except KeyboardInterrupt:
                sys.exit(0)
        hEscStatus.remove()
        hPeriodic.remove()

        
def createFig0():
#    plt.ion()
    fig0 = plt.figure(0)
    
    ax01 = fig0.add_subplot(111)
    ax01.plot([], [], 'bo')
    ax01.set_xlabel('pwm') #doesn't work, why?
    ax01.set_ylabel('rpm') #doesn't work, why?
    ax01.tick_params( axis='y', colors='b' )
    ax01.relim() 
    ax01.autoscale_view(True,True,True)
    
    ax02 = ax01.twinx()
    ax02.plot([], [], 'r')
    ax02.set_ylabel('current (A)') #doesn't work, why?
    ax02.tick_params( axis='y', colors='r' )
    ax02.relim() 
    ax02.autoscale_view(True,True,True)
    
    fig0.tight_layout()
    fig0.canvas.draw()
    
    return fig0, ax01, ax02


'''
Theory:
    Prop:
    S = c_S rho omega^2 D^4
    P_M = c_P rho omega^3 D^5
    P_M = M omega
    => 
    S^3 = pi/2 rho D^2 xi^2 P_M^2
    
    Motor:
    M \approx k I
    =>
    S^3 \approx pi/2 rho D^2 xi^2 k^2 I^2 omega^2 = c^3 (I omega)^2
    =>
    S(pwm) \approx c [I(pwm) omega(pwm)]^(2/3)
'''
def calculateThrust(record):
    pwm_scaled = []
    thrust = []
    for i in range(len(record.pwm)):
        pwm = record.pwm[i]
        pwm_scaled.append( pwm/8192.0 )
        current = record.current[i]
        omega = record.rpm[i] #we don't ned to convert to proper units, since only the exponent in the algebraic function is relevant
        thrust.append( math.pow(current*omega,2.0/3.0) )
        
    return pwm_scaled, thrust

    
def createFig1(pwm_scaled,thrust):
    fig1 = plt.figure(1)
    ax11 = fig1.add_subplot(111)
    ax11.plot( pwm_scaled, thrust, 'bo')
    ax11.plot( pwm_scaled, thrust, 'b')
    ax11.set_xlabel('scaled pwm')
    ax11.set_ylabel('estimated thrust (a.u.)')    
    
    fig1.canvas.draw()
    
    
def calculateNormalizedThrustCurve(_pwm,_thrust,MOT_SPIN_MIN=0.15,MOT_SPIN_MAX=0.95):
    pwm_norm = []
    thrust_norm = []
    pwm_min = 1.0e10
    pwm_max = 0.0
    thrust_max = 0.0
    for i in range(len(_pwm)):
        pwm = _pwm[i]
        if pwm < pwm_min: pwm_min = pwm
        if pwm > pwm_max: pwm_max = pwm
        thrust = _thrust[i]
        if thrust > thrust_max: thrust_max = thrust
    
    for i in range(len(_pwm)):
        pwm = _pwm[i]
        pwm_n = (pwm-pwm_min)/(pwm_max-pwm_min)
        if pwm_n < MOT_SPIN_MIN: continue
        if pwm_n > MOT_SPIN_MAX: continue
        pwm_norm.append( pwm_n )
        thrust = _thrust[i]
        thrust_norm.append( thrust/thrust_max )
        
    return pwm_norm, thrust_norm

    
def createFig23(pwm_norm,thrust_norm,fit=None):
    if fit:
        fig = plt.figure(3)
    else:    
        fig = plt.figure(2)
    ax = fig.add_subplot(111)
    ax.plot( pwm_norm, thrust_norm, 'bo')
    ax.plot( pwm_norm, thrust_norm, 'b')
    ax.set_xlabel('normalzed pwm')
    ax.set_ylabel('normalized thrust')
    if fit:
        ax.plot( pwm_norm, fit, 'ro')
    ax.set_xlim([0.0,1.0])    
    ax.set_ylim([0.0,1.0])    
    fig.canvas.draw()
    
'''
Theory
    from http://ardupilot.org/copter/docs/motor-thrust-scaling.html
    % Normalise the throttle and thrust
    throttle_normalised = (throttle_pwm(working_range) - min(throttle_pwm(working_range)))./(max(throttle_pwm(working_range))-min(throttle_pwm(working_range)));
    thrust_normalised = thrust./max(thrust);
    % Perform a least squares fit to solve for a in thrust = (1-a)*throttle + a*throttle^2
    mdl = @(a,x)((1-a(1))*x + a(1)*x.^2);
    startingVals = [0.5];
    coefEsts = nlinfit(throttle_normalised, thrust_normalised, mdl, startingVals);
    disp(['MOT_THST_EXPO is : ', num2str(coefEsts)]);
'''
def fitNormalizedThurstCurve(pwm_norm,thrust_norm):

    def func(x, a):
        return (1.0-a) * x + a * x*x
        
    '''
    thrust_norm = []
    for i in range(len(pwm_norm)): thrust_norm.append( func(pwm_norm[i],0.8) )        
    '''
    
    xdata = np.array(pwm_norm)
    ydata = np.array(thrust_norm)
        
    popt, pcov = curve_fit(func, xdata, ydata, p0=(0.5))    
    return popt[0], pcov[0][0]
    
        
def createNode(com):
    node = uavcan.make_node(com, node_id=126, bitrate=1000000, baudrate=1000000)

    node_monitor = uavcan.app.node_monitor.NodeMonitor(node)

#    dynamic_node_id_allocator = uavcan.app.dynamic_node_id.CentralizedServer(node, node_monitor)
#    while len(dynamic_node_id_allocator.get_allocation_table()) <= 1:
#        print('Waiting for other nodes to become online...')
#        node.spin(timeout=1)
        
    while len(node_monitor.get_all_node_id()) < 1:
        print('Waiting for other nodes to become online...')
        node.spin(timeout=1)
        
    all_node_ids = list(node_monitor.get_all_node_id())
    print( 'Detected Node IDs',all_node_ids)
    print( 'Node ID in use',all_node_ids[0])
    node_dict = node_monitor.get(all_node_ids[0]) #momentarily, always use the first, one shouldk use an ESC detection scheme as in the examples
    
    return node;

    
if __name__ == '__main__':

    node = createNode('COM38');
    
    print('press keyboard to start... ')
    while True:
        try:
            if msvcrt.kbhit():
                msvcrt.getch()
                break
        except KeyboardInterrupt:
            sys.exit(0)

    print('START Data recording... ')
    fig0, ax01, ax02 = createFig0()
    plt.show(block=False)
    record = cRecord(node, 3, fig0, ax01, ax02) #enter the desired esc index
    record.run()
    print('DONE')
    
    if len(record.pwm) > 2:
        print('calculating thrust curve... ')
        pwm_scaled, thrust = calculateThrust(record)
        #createFig1(pwm_scaled, thrust)
        print('DONE')
        
        print('calculating normalized thrust curve... ')
        pwm_norm, thrust_norm = calculateNormalizedThrustCurve(pwm_scaled, thrust, 0.15, 0.95)
        createFig23(pwm_norm, thrust_norm)
        print('DONE')
        
        print('fitting normalized thrust curve... ')
        popt, pcov = fitNormalizedThrustCurve(pwm_norm, thrust_norm)
        print(popt,pcov)
        fit = []
        for i in range(len(pwm_norm)): fit.append( func(pwm_norm[i],popt) )        
        createFig23(pwm_norm, thrust_norm, fit)
        print('DONE')
            
    
    plt.show(block=True)
