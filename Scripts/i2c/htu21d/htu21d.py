#!/usr/bin/python
#
# chris@crHARPER.com
# JAN 29, 2018
#
# Measurment Specialties HTU21D Temperature/Humidity sensor
# Raspberry Pi
#
#
#
import os
import time
from smbus import SMBus
from math import log10

I2CBUS = 1

#-----------------------------------------------------------------------------
# HTU21D Measurement Specialties Temperature & Humidity Sensor
#-----------------------------------------------------------------------------
HTU21D_ADDR = 0x40

# Instruction Byte
HTU21D_READ_TEMP_HOLD = 0xe3
HTU21D_READ_HUM_HOLD = 0xe5
HTU21D_READ_TEMP_NOHOLD = 0xf3
HTU21D_READ_HUM_NOHOLD = 0xf5
HTU21D_WRITE_USER_REG = 0xe6
HTU21D_READ_USER_REG = 0xe7
HTU21D_SOFT_RESET= 0xfe

# Data bits specification
HTU21D_STATUS_BITMASK     = 0b00000011
HTU21D_STATUS_TEMPERATURE = 0b00000000
HTU21D_STATUS_HUMIDITY    = 0b00000010
HTU21D_STATUS_LSBMASK     = 0b11111100

# Maintain a 3 reading per minute moving average
HTU21D_MAX = 3
HTU21D_MAX_FLOAT = 3.0

CRC_HTU = 0x00      # Instrumant Specialties HTU21D RH sensor
CRC_SGP = 0xff      # Senserion VOC sensor


#-----------------------------------------------------------------------------
# HTU21D Measurement Specialties Temperature Humidity Sensor
#-----------------------------------------------------------------------------
class HTU21D:
    
    def __init__(self, name, i2c_addr):
        self.I2Caddr = i2c_addr
        
        directory = "/tmp/" + name
        if not os.path.exists(directory):
            os.makedirs(directory)

        self.FptrTC = directory + "/tc"
        self.FptrRH = directory + "/rh"
        self.FptrTD = directory + "/td"
        self.FptrAH = directory + "/ah"
        
        # For file handeling, maintaining the moving averages
        self.temp_buff  = [ 0 ] * HTU21D_MAX
        self.temp_ptr   = 0
        self.humid_buff = [ 0 ] * HTU21D_MAX
        self.humid_ptr  = 0  

        self.init_buff = 1 # flag to fill buffers
        
        bus = SMBus(I2CBUS)
        bus.write_byte( self.I2Caddr, HTU21D_SOFT_RESET )
        time.sleep(0.015)        
        bus.close()
    
    
    #-----------------------------------------------------------------------------
    # CRC8 calculation for the HTU21D sensor
    #-----------------------------------------------------------------------------
    # Need to provide device specific initial value: 
    def crc8( self, value ):
        crc = CRC_HTU
        POLY = 0x31

        for x in range(len(value)):
            crc = crc ^ value[x]
            for y in range(8):
                if (crc & 0x80):
                    crc = crc << 1
                    crc = crc ^ POLY
                else:
                    crc = crc << 1
            crc = crc & 0xff
            
        #print "htu21d.crc8() crc: 0x%02x" % crc        
        
        return crc
        
        
    #-----------------------------------------------------------------------------
    # HTU21D Task
    #-----------------------------------------------------------------------------
    # Call every 20 seconds
    def task(self):

        temp  = 99999
        humid = 99999
        tdew  = 99999
        
        status = 0
        
        try:

            bus = SMBus(I2CBUS)
            resp = bus.read_i2c_block_data( self.I2Caddr, HTU21D_READ_TEMP_HOLD, 3 )
            if ( self.crc8(resp) == 0 ):
                status += 1
                # data sheet 15/21 Temperature Conversion
                t = (resp[0] << 8) | (resp[1] & HTU21D_STATUS_LSBMASK)
                temp = ((175.72 * t) / 65536.0) - 46.86 

                self.temp_buff[self.temp_ptr] = temp
                self.temp_ptr += 1
                if self.temp_ptr >= HTU21D_MAX:
                    self.temp_ptr = 0

                # runs first pass only
                if self.init_buff :
                    for i in range(HTU21D_MAX):
                        self.temp_buff[i] = temp
                # need to init humid_buff[] too
                # so don't clear self.init_buff flag here
            
                avg_temp = 0
                for i in range(HTU21D_MAX):
                    avg_temp += self.temp_buff[i]
                avg_temp /= HTU21D_MAX_FLOAT

                f = open(self.FptrTC,"w")
                f.write("%3.1f" % avg_temp)
                f.close()

            resp = bus.read_i2c_block_data( self.I2Caddr, HTU21D_READ_HUM_HOLD, 3 )
            bus.close()
            if( self.crc8( resp ) == 0 ):
                status += 1
                # data sheet 15/21 Relative Humidity
                h = (resp[0] << 8) | (resp[1] & HTU21D_STATUS_LSBMASK)
                humid = ((125.0 * h) / 65536.0) - 6.0 
            
                # limit for out of range values
                # per data sheet page 15/21
                if humid < 0.0 :
                    humid = 0.0
                if humid > 100.0:
                    humid = 100.0
                
                # RH compensation per datasheet page: 4/12    
                rh = humid + ( 25.0 - temp) * -0.15    

                self.humid_buff[self.humid_ptr] = rh
                self.humid_ptr += 1
                if self.humid_ptr >= HTU21D_MAX:
                    self.humid_ptr = 0
            
                # runs first pass only
                if self.init_buff :
                    for i in range(HTU21D_MAX):
                        self.humid_buff[i] = rh
                        self.init_buff = 0
           
                avg_humid = 0
                for i in range(HTU21D_MAX):
                    avg_humid += self.humid_buff[i]
                avg_humid /= HTU21D_MAX_FLOAT

                f = open(self.FptrRH,"w")
                f.write("%3.1f" % avg_humid)
                f.close()
    
            # with both valid temperature and RH 
            # calculate the dew point and absolute humidity using average values
            if status == 2:
            
                # Calculate dew point
            
                # because log of zero is not possible
                if avg_humid < 0.1:
                    avg_humid = 0.1
                A = 8.1332
                B = 1762.39
                C = 235.66
                # data sheet page 16/21 Partial Pressure & Dew Point  
                pp = 10**( A - ( B / ( avg_temp + C )))            
                tdew = -(( B / ( log10( avg_humid * pp / 100.0) - A )) + C ) 
            
                f = open(self.FptrTD,"w")
                f.write("%3.1f" % tdew)
                f.close()

                # Calculate absolute humidity in grams/M^3
                e = 2.71828
                a = 13.2473
                b = e**((17.67 * avg_temp)/(avg_temp + 243.5))
                c = 273.15 + avg_temp
                ah = a * b * avg_humid / c
            
                f = open(self.FptrAH,"w")
                f.write("%3.1f" % ah)
                f.close()

            print "htu21d.task() T: %3.1f RH: %3.1f Tdew: %3.1f AH: %3.1f" %  ( avg_temp, avg_humid, tdew, ah )
        
        except:
            print "htu21d.task() error"
            
        # returning average values
        return [ temp, humid, tdew, ah ]        
