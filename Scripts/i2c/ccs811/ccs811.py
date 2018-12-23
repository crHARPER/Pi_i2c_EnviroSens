#!/usr/bin/python
#
# chris@crHARPER.com
# JAN 29, 2018
#
# AMS CCS811 VOC sensor
# Raspberry Pi
#
#
#
import os
import time
from smbus import SMBus

I2CBUS = 1

#------------------------------------------------------------------------------
# AMS CCS811 VOC Sensor
#------------------------------------------------------------------------------
CCS811_ADDR = 0x5a
#
# Registers
CCS811_REG_STATUS    = 0x00
CCS811_REG_MEAS_MODE = 0x01
CCS811_REG_RESULTS   = 0x02
CCS811_REG_ENV_DATA  = 0x05
CCS811_REG_BASELINE  = 0x11
CCS811_REG_ERROR     = 0xe0
#
CCS811_HW_ID         = 0x20
CCS811_VER_HW        = 0x21
CCS811_VER_BOOT      = 0x23
CCS811_VER_APP       = 0x24
#
CCS811_APP_START     =0xF4
#
# Status Bits
CCS811_STATUS_DATA_RDY = 0x08
CCS811_STATUS_ERROR    = 0x01
CCS811_APP_VALID       = 0x10
#
# Measure once every seconds, no interupts, no thresholds
CCS811_MEAS_MODE_OFF = 0x00
CCS811_MEAS_MODE_ON  = 0x10 # continuous power, once per second updates 
# Tried every 10 seconds, pulsed mode but readings seemed unstable
#
CCS811_T_MAX = 5
CCS811_T_MAX_FLOAT = 5.0
#
CCS811_MAX = 3
CCS811_MAX_FLOAT = 3.0
#
#
#------------------------------------------------------------------------------
# AMS CCS811 VOC Sensor
#------------------------------------------------------------------------------
class CCS811:

    def __init__(self, name, i2c_addr):
        self.I2Caddr   = i2c_addr
        
        directory = "/tmp/" + name
        if not os.path.exists(directory):
            os.makedirs(directory)

        self.FptrVoc   = directory + "/voc"
        self.FptrBase  = directory + "/base"
        self.FptrError = directory + "/error"
        
        # to retreave RH values for compensation
        self.FptrTemp  = "/tmp/HTU21D/tc"
        self.FptrHumid = "/tmp/HTU21D/rh"
        
        # for maintaining the moving averages
        self.voc_buff  = [ 0 ] * CCS811_MAX
        self.voc_ptr   = 0
        
        # for tracking baseline value changes
        self.newcal = 0
        self.oldcal = 0
        # to track RH compenation event
        self.comp_minute = CCS811_T_MAX
        # Long term T & RH averaging 
        self.temp_buff = [ 23 ] * CCS811_T_MAX
        self.rh_buff = [ 50 ] * CCS811_T_MAX
    
        bus = SMBus(I2CBUS)
        resp = bus.read_byte_data( self.I2Caddr, CCS811_REG_STATUS )
        print "ccs811.init() status reg: 0x%02x" % resp
        if resp & CCS811_APP_VALID:
            bus.write_byte( self.I2Caddr, CCS811_APP_START )
            print "ccs811.init() starting application"
        else:
            print "ccs811.init() failed to start application"
            bus.close()
            sys.exit( 10 )

        time.sleep(1)

        # Start making measurements
        bus.write_byte_data( self.I2Caddr, CCS811_REG_MEAS_MODE, CCS811_MEAS_MODE_ON )
        resp = bus.read_byte_data(self.I2Caddr, CCS811_REG_ERROR )
        if resp:
            print "ccs811.init() error reg: 0x%02x" % resp
            sys.exit ( 11 )

        # Display CCS811 information on startup
        resp = bus.read_byte_data( self.I2Caddr, CCS811_HW_ID )
        print "ccs811.inint() HW ID: 0x%02x" % resp
        resp = bus.read_byte_data( self.I2Caddr, CCS811_VER_HW )
        print "ccs811.inint() HW Ver: 0x%02x" % resp
        resp = bus.read_i2c_block_data( self.I2Caddr, CCS811_VER_APP, 2 )
        major = resp[0] & 0xf0 >> 4
        minor = resp[0] & 0x0f
        trivial = resp[1]
        print "css811.init() app ver: %d.%d.%d" % ( major, minor, trivial ) 

        resp = bus.read_byte_data( self.I2Caddr, CCS811_REG_ERROR )
        if resp:
            print "ccs811.init() error reg: 0x%02x" % resp
            sys.exit( 12 )

        # Init envronmental compensation registers
        temp_c = 23
        r_humidity = 50
        self.set_comp( temp_c, r_humidity )
        # will implement periodically in loop
        #print "CCS811 init complete"
        bus.close()

    #-----------------------------------------------------------------------------
    # This sets the CCS811 environmental compensation 
    #-----------------------------------------------------------------------------
    # usually called by comp_task() or __init__()
    def set_comp( self, t, h ):
        
        # don't know if a value of 0.0% RH is allowed
        # so make minimun RH 0.01%
        if h < 0.1:
            h = 0.01
            
        if t < -25.0:
            t = -25.0
        
        rh = h * 2.0
        rh_i = int( rh // 1 )
        rh_i &= 0xff
        #rh_d = int( (rh % 1) * 256 )
        # per CC-803-AN rev 6, AMS writes zero to fractional byte
        rh_d = 0x00

        # per datasheet 25 degree offset 
        th = ( t + 25 ) * 2.0
        th_i = int( th // 1 )
        th_i &= 0xff
        #th_d = int( (th % 1) * 256 )
        # per CC-803-AN tev 6, AMS writes zero to fractional byte
        th_d = 0x00

        msg = [ rh_i, rh_d, th_i, th_d ]
        
        print "ccs811.set_comp() set T: %.1f RH: %.1f" % ( t, h )
        print "ccs811.set_comp() regs. 0x%02x 0x%02x 0x%02x 0x%02x" % ( th_i, th_d, rh_i, rh_d )

        bus = SMBus(I2CBUS)
        bus.write_i2c_block_data( self.I2Caddr, CCS811_REG_ENV_DATA, msg )
        bus.close()
        return
        
        
    #-----------------------------------------------------------------------------
    # Averages environmental data and then periodically applies it to CCS811
    #----------------------------------------------------------------------------- 
    # run task once a minute
    def comp_task(self):
    
        # Try to read the externally expected temperature and humidity files
        try:
            file = open( self.FptrTemp, "r")
            c = float( file.read() )
            file.close()
            
            file = open( self.FptrHumid, "r")
            rh = float( file.read() )
            file.close()
            
            # just making sure T & RH values look okay befor proceeding
            if c < 40 and rh < 100 and rh >= 0:
                self.comp_minute -= 1
                self.temp_buff[self.comp_minute] = c
                self.rh_buff[self.comp_minute] = rh
                print "ccs811.comp_task() minute T: %.1f RH: %.1f" % (c, rh)

                if self.comp_minute == 0:

                    # calculate averages and set CCS811 compensation
                    avg_c  = 0
                    avg_rh = 0
                    for i in range(CCS811_T_MAX):
                        avg_c += self.temp_buff[i]
                        avg_rh += self.rh_buff[i]
                        
                    avg_c  /= CCS811_T_MAX_FLOAT
                    avg_rh /= CCS811_T_MAX_FLOAT

                    self.set_comp(avg_c, avg_rh)                    
                    self.comp_minute = CCS811_T_MAX

        except:
            print "ccs811.comp_task() can't read T & RH files"    
        
        
        
    #-----------------------------------------------------------------------------
    # 
    #-----------------------------------------------------------------------------        
    def get_baseline(self):
    # Looks like on power up, the CCS811 keeps
    # adjusting its baseline possibly bacause
    # the calculated tVOC value is negitive.
    # In effect the chip is auto zeroing itself.
        bus = SMBus(I2CBUS)
        resp = bus.read_i2c_block_data( self.I2Caddr, CCS811_REG_BASELINE, 2 )
        bus.close()
        bl = (resp[0] << 8) | resp[1]
        #print "Baseline: 0x%04x" % bl
        return bl


    #-----------------------------------------------------------------------------
    # 
    #-----------------------------------------------------------------------------
    def set_baseline( self, hi, lo ):
        msg = [ hi, lo ]

        bus = SMBus(I2CBUS)
        resp = bus.write_i2c_block_data( self.I2Caddr, CCS8_REG_BASELINE, msg )
        bus.close()
        return


    #-----------------------------------------------------------------------------
    # 
    #-----------------------------------------------------------------------------
    def error_reg(self):
        bus = SMBus(I2CBUS)
        resp = bus.read_byte_data( self.I2Caddr, CCS811_REG_ERROR )
        bus.close()
        return resp


    #-----------------------------------------------------------------------------
    # 
    #-----------------------------------------------------------------------------
    def task(self):
        
        avg_voc = 99999

        try:
            
            # see if an update is ready
            bus = SMBus(I2CBUS)
            resp = bus.read_byte_data( self.I2Caddr, CCS811_REG_STATUS )
            bus.close()

            if resp & CCS811_STATUS_DATA_RDY:
                bus = SMBus(I2CBUS)
                resp = bus.read_i2c_block_data( self.I2Caddr, CCS811_REG_RESULTS, 4 )
                bus.close()
                #e_co2 = (resp[0] << 8) | resp[1] 
                t_voc = (resp[2] << 8) | resp[3]

                # make sure reading looks to be within range
                # 1187ppb is max possible 
                if t_voc < 1200:
                    self.voc_buff[self.voc_ptr] = t_voc
                    self.voc_ptr += 1
                    if self.voc_ptr >= CCS811_MAX:
                        self.voc_ptr = 0

                    # calculate current average voc value
                    # 3 samples per minute
                    avg_voc = 0
                    for i in range(CCS811_MAX):
                        avg_voc += self.voc_buff[i]
                    avg_voc /= CCS811_MAX_FLOAT
                    avg_voc = int(round(avg_voc))
                
                    print "ccs811.task() avg voc: %d" % avg_voc        

                    f = open(self.FptrVoc,"w")
                    f.write("%d" % avg_voc)
                    f.close()

                    self.newcal = self.get_baseline()
                    if self.newcal != self.oldcal:
                        print "ccs811.task() new baseline: 0x%04x" % self.newcal
                        f = open(self.FptrBase,"w")
                        f.write("0x%04x" % self.newcal)
                        f.close()
                        self.oldcal = self.newcal

                    err = self.error_reg()
                    if err:
                        print "ccs811.task() error reg: 0x%02x" % resp[0]
                        f = open(self.FptrError,"w")
                        f.write("0x%02x" % err)
                        f.close()
                    
                # returning latest value, not average
                return t_voc        
            else:
                print "ccs811.task() not ready yet 0x%02x" % resp[0]
                return 99999
                
        except:
            print "ccs811.tast() error"
            return 99999
            

    #-----------------------------------------------------------------------------

