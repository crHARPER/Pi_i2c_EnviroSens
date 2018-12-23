#!/usr/bin/python
#
# chris@crHARPER.com
# JAN 29, 2018
#
# NOV 27, 2018 Revision to AH compensation
# DEC 03, 2018 Added Serial ID and now writing Version to file system
#
# Sensirion SGP30 VOC sensor
# running on a Raspberry Pi
# 
# Depends on HTU21D writing to file system for gathering
# Absolute Humidity Values in self.comp_task()
#
#
import os
import time
from smbus import SMBus

I2CBUS = 1

#-----------------------------------------------------------------------------
# SGP30 Sensirion VOC Sensor
#-----------------------------------------------------------------------------
SGP30_ADDR = 0x58
#

# Serial ID Address
SGP30_SID_MSB = 0x36
SGP30_SID_LSB = 0x82

# MSB of Instuction
SGP30_MSB  = 0x20 
# LSB of Instruction
SGP30_INIT     = 0x03
SGP30_MEASURE  = 0x08
SGP30_GET_BASE = 0x15
SGP30_SET_BASE = 0x1e
SGP30_SET_AH   = 0x61    # Absolute Humidity
SGP30_GET_VERSION = 0x2f
SGP30_MEASURE_RAW = 0x50 # H2 then Ethanol values
#
# Maintain a 1 minute moving average
SGP30_MAX = 60
SGP30_MAX_FLOAT = 60.0
# compensate every five minutes
SGP30_T_MAX = 5
SGP30_T_MAX_FLOAT = 5.0
#
CRC_HTU = 0x00      # Instrumant Specialties HTU21D RH sensor
CRC_SGP = 0xff      # Senserion VOC sensor
#
#-----------------------------------------------------------------------------
# SGP30 Sensirion VOC Sensor
#-----------------------------------------------------------------------------
class SGP30:

    def __init__(self, name, i2c_addr):
        self.I2Caddr = i2c_addr             # i2c address
        
        directory = "/tmp/" + name
        if not os.path.exists(directory):
            os.makedirs(directory)
        
        
        self.FptrVoc = directory + "/voc" # filename for voc value in /tmp
        self.FptrBaseC = directory + "/base_c"
        self.FptrBaseV = directory + "/base_v"
        self.FptrAH = directory + "/ah"
        # raw sensor values
        self.FptrH2 = directory + "/h2"
        self.FptrET = directory + "/et" 
        # device serial number
        self.FptrSID = directory + "/sid"
        self.FptrVer = directory + "/ver"
        
        # to retreave Absolute Humidity value for compensation
        self.FptrHTU21D_AH = "/tmp/HTU21D/ah"
        
        # to track RH compenation event
        self.comp_minute = SGP30_T_MAX
        # Long term AH averaging 
        self.ah_buff = [ 10.28 ] * SGP30_T_MAX
        # one minute averaging buffer
        self.voc_buff = [0] * SGP30_MAX
        self.voc_ptr = 0
        
        # for raw sensor values
        self.h2_buff = [0] * SGP30_MAX
        self.et_buff = [0] * SGP30_MAX
        self.raw_ptr = 0
        
        self.get_sid()     # serial number
        self.get_version() # firmware 

        #-----------------------------------------------------------------------------
        # Upon power-up, initilized the SGP30 sensor
        #-----------------------------------------------------------------------------
        bus = SMBus(I2CBUS)
        bus.write_byte_data( self.I2Caddr, SGP30_MSB, SGP30_INIT )
        time.sleep(0.01)
        bus.close()
        
        # Init envronmental compensation registers
        ah = 10.28 # equal to T:23c & RH: 50% 
        self.set_comp( ah )
        # will implement periodically in loop
        time.sleep(0.01)
        

    #-----------------------------------------------------------------------------
    # CRC8 calculation for the SGP30 sensor
    #-----------------------------------------------------------------------------
    # Need to provide device specific initial value: 
    def crc8( self, value ):
        crc = CRC_SGP
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

        #print "sgp30.crc8() crc: 0x%02x" % crc

        return crc


    #-----------------------------------------------------------------------------
    # Do periodic temperature & humidity compensation
    #-----------------------------------------------------------------------------
    # usually called by comp_task() and __init__()
    def set_comp( self, ah ):

        msg = [ SGP30_SET_AH ] # start with command LSB

        # we don't want to completely turn off compensation when humididty is very low
        # per datasheet page 8/15 minimum value is 1/256 g/M^3
        #if ah < 0.1:
        #    ah = 0.01
        
        # Enviro's very low winter time AH values may be causing large baseline offsets
        # testing limiting minimum AH value to 1g/M^3
        if ah < 1.0: 
            ah = 1.0

        ah_i = int( ah // 1) 	        # integer byte
        ah_i &= 0xff
        ah_d = int( (ah % 1) * 256.0 ) # decimal byte
        ah_d &= 0xff   

        ah_comp = [ ah_i, ah_d ]       # in SGP30 format
        ah_crc = self.crc8( ah_comp )

        # addend crc byte
        ah_comp.append( ah_crc )
        # add AH data list to message list
        msg.extend(ah_comp)

        print "sgp30.set_comp(): set AH: %.1f" % ( ah )
        print "sgp30.set_comp(): AH regs. 0x%02x 0x%02x" % ( ah_i, ah_d )

        bus = SMBus(I2CBUS)
        resp = bus.write_i2c_block_data( self.I2Caddr, SGP30_MSB, msg )
        bus.close()
        time.sleep(0.01)
        
        # log AH value
        f = open(self.FptrAH,"w")
        f.write("%3.1f" % ah)
        f.close()
        
        
    #-----------------------------------------------------------------------------
    # Averages absolute humidity values and then periodically applies it to SGP30
    #----------------------------------------------------------------------------- 
    # run task once a minute
    def comp_task(self):
        # Try to read the externally expected temperature and humidity files
        try:
            file = open( self.FptrHTU21D_AH, "r")
            ah = float( file.read() )
            file.close()
            
            # make sure AH value looks okay before proceeding            
            if ah < 100 and ah >= .1 :
                self.comp_minute -= 1
                self.ah_buff[self.comp_minute] = ah
                print "sgp30.comp_task(): minute AH: %3.1f" % ( ah )

                if self.comp_minute == 0:

                    # calculate averages and set CCS811 compensation
                    avg_ah  = 0
                    for i in range(SGP30_T_MAX):
                        avg_ah += self.ah_buff[i]
                    avg_ah  /= SGP30_T_MAX_FLOAT
                    
                    self.set_comp( avg_ah )
                    self.comp_minute = SGP30_T_MAX
                    
        except:
            print "sgp30.comp_task(): can't read AH file"    


    #-----------------------------------------------------------------------------
    # Get internal auto calibration and write to file system 
    #-----------------------------------------------------------------------------        
    def get_baseline(self):
        # eCO2 baseline word first + crc
        # tVOC baseline word second + crc       
        # these two lists need to be in reverse order for setting baseline
        bus = SMBus(I2CBUS)
        bus.write_byte_data( self.I2Caddr, SGP30_MSB, SGP30_GET_BASE )
        time.sleep(0.02)
        resp = bus.read_i2c_block_data( self.I2Caddr, 0, 6 )
        bus.close()
        
        # Because there are two set of baselines we will just
        # write them directly to the file-system instead of
        # looking for changes
        
        baseline_co2 = [ resp[0], resp[1], resp[2] ]
        baseline_voc = [ resp[3], resp[4], resp[5] ]
        
        if ( self.crc8( baseline_co2 ) == 0 ):
            # comma delimited output
            #msg = str(baseline_co2).strip('[]')
            bl = ( resp[0] << 8 ) | resp[1]
            f = open(self.FptrBaseC,"w")
            f.write("%d" % bl)
            f.close()
            
            print "sgp30.get_baseline() co2: 0x%04x" % bl
            
        if ( self.crc8( baseline_voc ) == 0 ):
            # comma delimited output
            #msg = str(baseline_voc).strip('[]')
            bl = ( resp[3] << 8 ) | resp[4]
            f = open(self.FptrBaseV,"w")
            f.write("%d" % bl)
            f.close()
            
            print "sgp30.get_baseline() voc: 0x%04x" % bl
            
    
    #-----------------------------------------------------------------------------
    # On a restart, can set to previous baselines to reduce stabilization time
    #----------------------------------------------------------------------------- 
    # !!This Method Has Not Been Verified!!     
    def set_baseline( self, baseline_voc, baseline_co2 ):
        # tVOC baseline word first + crc
        # eCO2 baseline word second + crc
        baseline = [0x00] * 2
                
        msg = [ SGP30_SET_BASE ] # start with command LSB
        
        # VOC first
        baseline[0] = (baseline_voc & 0xff00) >> 8
        baseline[0] &= 0xff
        baseline[1] = baseline_voc & 0xff
        msg.extend(baseline)
        msg.append( self.crc8(baseline) )
        
        # Then eCO2
        baseline[0] = (baseline_co2 & 0xff00) >> 8
        baseline[0] &= 0xff
        baseline[1] = baseline_co2 & 0xff
        msg.extend(baseline)
        msg.append( self.crc8(baseline) )

        print "sgp30.set_baseline() voc baseline: %02x %02x crc: %02x" % ( msg[1], msg[2], msg[3] )
        print "sgp30.set_baseline() co2 baseline: %02x %02x crc: %02x" % ( msg[4], msg[5], msg[6] )
        
        bus = SMBus(I2CBUS)
        resp = bus.write_i2c_block_data( self.I2Caddr, SGP30_MSB, msg )
        bus.close()
        time.sleep(0.01)


    #-----------------------------------------------------------------------------
    # Get feature set & version 
    #-----------------------------------------------------------------------------        
    def get_version(self):
        
        bus = SMBus(I2CBUS)
        bus.write_byte_data( self.I2Caddr, SGP30_MSB, SGP30_GET_VERSION )
        time.sleep(0.01)
        resp = bus.read_i2c_block_data( self.I2Caddr, 0, 3 )
        bus.close()
        
        if ( self.crc8( resp ) == 0 ):
            print "sgp30.get_version() Feature Set Type: 0x%02x Version: 0x%02x" % ( resp[0], resp[1] )
            
            info = (resp[0] << 8) | resp[1]
                
            #log Feature & Version Info
            f = open(self.FptrVer,"w")
            f.write("%d" % info)
            f.close()
        
        return info
    

    #-----------------------------------------------------------------------------
    # Get Serial ID
    #-----------------------------------------------------------------------------
    def get_sid(self):
        
        info = [ 0xffff ] * 3
        test = 0
    
        bus = SMBus(I2CBUS)
        bus.write_byte_data( self.I2Caddr, SGP30_SID_MSB, SGP30_SID_LSB )
        time.sleep(0.01)
        
        resp = bus.read_i2c_block_data( self.I2Caddr, 0, 9 )
        bus.close()

        sid_1 = [ resp[0], resp[1], resp[2] ]
        sid_2 = [ resp[3], resp[4], resp[5] ]
        sid_3 = [ resp[6], resp[7], resp[8] ]

        if ( self.crc8( sid_1 ) == 0 ):
            info[0] = (sid_1[0] << 8 ) | sid_1[1]
            test += 1
            
        if ( self.crc8( sid_2 ) == 0 ):
            info[1] = (sid_2[0] << 8) | sid_2[1]
            test += 1            

        if ( self.crc8( sid_3 ) == 0 ):
            info[2] = (sid_3[0] << 8) | sid_3[1]   
            test += 1
        
        if test == 3:
            sid = (info[0] << 32) | (info[1] << 16) | info[2]
            print "sgp30.get_sid(): 0x%012x" % ( sid )  
            
            #log Serial ID
            f = open(self.FptrSID,"w")
            f.write("%d" % sid)
            f.close()
        else:
            print "sgp30.get_sid(): failed"
        
        return info
            
            
    #-----------------------------------------------------------------------------
    # Get raw H2 and Ethanol values from Sensirion SGP30 sensor
    #-----------------------------------------------------------------------------
    # should be run once per second if used
    def raw(self):
    
        h2 = 99999 # Hydrogen
        et = 99999 # Ethanol
        test = 0
        
        bus = SMBus(I2CBUS)
        bus.write_byte_data( self.I2Caddr, SGP30_MSB, SGP30_MEASURE_RAW )
        time.sleep(0.03)
        resp = bus.read_i2c_block_data( self.I2Caddr, 0, 6 )
        bus.close()
        
        # raw sensor values
        # bytes 0-2 are H2 + CRC8
        # bytes 3-5 are Ethanol + CRC8
        temp = [ resp[0], resp[1], resp[2] ]
        if ( self.crc8( temp ) == 0 ):
            h2 = (resp[0] << 8) | resp[1]
            # maintain 1 minute moving average buffer
            self.h2_buff[ self.raw_ptr ] = h2
            test += 1
                
        temp = [ resp[3], resp[4], resp[5] ]
        if ( self.crc8( temp ) == 0 ):
            et = (resp[3] << 8) | resp[4]
            # maintain 1 minute moving average buffer
            self.et_buff[ self.raw_ptr ] = et
            test += 1
                
        # every 20 seconds write to file system
        if (self.raw_ptr % 20 == 0 ):             
            
            # calculate current average voc value
            # 60 samples per minute
            avg_h2 = 0
            avg_et = 0
            for i in range( SGP30_MAX ):
                avg_h2 += self.h2_buff[i]
                avg_et += self.et_buff[i]
            avg_h2 /= SGP30_MAX_FLOAT
            avg_et /= SGP30_MAX_FLOAT
            avg_h2 = int(round( avg_h2 ))
            avg_et = int(round( avg_et ))
            
            print "sgp30.raw() h2 avg: %d ethanol avg: %d" % ( avg_h2, avg_et )
                
            f = open(self.FptrH2,"w")
            f.write("%d" % avg_h2)
            f.close()
                
            f = open(self.FptrET,"w")
            f.write("%d" % avg_et)
            f.close()
            
        # only if all data is valid, do we increment the pointer            
        if test == 2:
            self.raw_ptr += 1
            if self.raw_ptr >= SGP30_MAX:
                self.raw_ptr = 0   
        
            
        # returning latest value, not average
        return [ h2, et ]
        
        
    #-----------------------------------------------------------------------------
    # Get tVOC reading from Sensirion SGP30 sensor
    #-----------------------------------------------------------------------------
    # should be run once per second
    def task(self):
    
        tvoc = 99999
        
        try:
            bus = SMBus(I2CBUS)
            bus.write_byte_data( self.I2Caddr, SGP30_MSB, SGP30_MEASURE )
            time.sleep(0.02)
            resp = bus.read_i2c_block_data( self.I2Caddr, 0, 6 )
            bus.close()
            # Only care about tVOC since eCO2 is just that
            # bytes 0-2 are eCO2 + CRC8
            # bytes 3-5 are tVOC + CRC8
            temp = [ resp[3], resp[4], resp[5] ]
            if ( self.crc8( temp ) == 0 ):
                t_voc = (resp[3] << 8) | resp[4]
            
                # maintain 1 minute moving average buffer
                self.voc_buff[ self.voc_ptr ] = t_voc
                
                # every 20 seconds write to file system
                if (self.voc_ptr % 20 == 0 ): 
                    # calculate current average voc value
                    # 60 samples per minute
                    avg_voc = 0
                    for i in range( SGP30_MAX ):
                        avg_voc += self.voc_buff[i]
                    avg_voc /= SGP30_MAX_FLOAT
                    avg_voc = int(round( avg_voc ))      
            
                    print "sgp30.task() voc: %d avg: %d " % ( t_voc, avg_voc )
                
                    f = open(self.FptrVoc,"w")
                    f.write("%d" % avg_voc)
                    f.close()
                
                self.voc_ptr += 1
                if self.voc_ptr >= SGP30_MAX:
                    self.voc_ptr = 0   
                    
            # returning latest value, not average
            return t_voc
            
        except:
            print "sgp30.task() error"
            return 99999