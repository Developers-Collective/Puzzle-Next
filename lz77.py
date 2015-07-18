import struct
import ctypes

class LZS11(object):
    def __init__(self):
    	self.magic = 0x11
    	self.decomp_size = 0
    	self.curr_size = 0
    	self.compressed = True
    	self.outdata = []
    def Decompress11LZS( self , filein ):
    	offset = 0
    	# check that file is < 2GB
    	#print "length of file: 0x%x" % len(filein)
    	assert len(filein) < ( 0x4000 * 0x4000 * 2 )
    	self.magic = struct.unpack('<B', filein[0:1])[0]
    	#print "magic = 0x%x" % self.magic
    	assert self.magic == 0x11
    	self.decomp_size = struct.unpack('<I', filein[offset:offset+4])[0] >> 8
    	offset += 4
    	assert self.decomp_size <= 0x200000
    	if ( self.decomp_size == 0 ):
    		self.decomp_size = struct.unpack('<I', filein[offset:offset+4])[0]
    		offset += 4
    	assert self.decomp_size <= 0x200000 << 8
    
    	#print "Decompressing 0x%x. (outsize: 0x%x)" % (len(filein), self.decomp_size)
    	self.outdata = [0 for x in range(self.decomp_size)]
    
    	while self.curr_size < self.decomp_size and offset < len(filein):
    		flags = struct.unpack('<B', filein[offset:offset+1])[0]
    		offset += 1
    
    		for i in range( 8 ):
    			x = 7 - i
    			if self.curr_size >= self.decomp_size:
    				break
    			if (flags & (1 << x)) > 0:
    				first = struct.unpack('<B', filein[offset:offset+1])[0]
    				offset += 1
    				second = struct.unpack('<B', filein[offset:offset+1])[0]
    				offset += 1
    
    				if first < 0x20:
    					third = struct.unpack('<B', filein[offset:offset+1])[0]
    					offset += 1
    
    					if first >= 0x10:
    						fourth = struct.unpack('<B', filein[offset:offset+1])[0]
    						offset += 1
    
    						pos = (((third & 0xF) << 8) | fourth) + 1
    						copylen = ((second << 4) | ((first & 0xF) << 12) | (third >> 4)) + 273
    					else:
    						pos = (((second & 0xF) << 8) | third) + 1
    						copylen = (((first & 0xF) << 4) | (second >> 4)) + 17
    				else:
    					pos = (((first & 0xF) << 8) | second) + 1
    					copylen = (first >> 4) + 1
    
    				for y in range( copylen ):
    					self.outdata[self.curr_size + y] = self.outdata[self.curr_size - pos + y]
    
    				self.curr_size += copylen
    			else:
    
    				self.outdata[self.curr_size] = struct.unpack('<B', filein[offset:offset+1])[0]
    				offset += 1
    				self.curr_size += 1
    
    			if offset >= len(filein) or self.curr_size >= self.decomp_size:
    				break
    	return self.outdata

    def Compress11LZS(self, data):
        dcsize = len(data)
        cbuffer = ctypes.create_string_buffer(0x1000000)
        
        src = 0
        dest = 4
        
        if dcsize > 0xFFFFFFFF: return None
        
        lzdict = LzWindowDictionary()
        lzdict.setWindowSize(0x1000)
        lzdict.setMaxMatchAmount(0xFFFF + 273)
        
        cbuffer[0] = b'\x11'
        func_chr = lambda val: bytes((val,))
        
        if dcsize <= 0xFFFFFF:
            cbuffer[1] = func_chr(dcsize & 255)
            cbuffer[2] = func_chr((dcsize >> 8) & 255)
            cbuffer[3] = func_chr((dcsize >> 16) & 255)
        else:
            return None
            #cbuffer[4] = chr(dcsize & 255)
            #cbuffer[5] = chr((dcsize >> 8) & 255)
            #cbuffer[6] = chr((dcsize >> 16) & 255)
            #cbuffer[7] = chr((dcsize >> 24) & 255)
            #dest += 4
        
        flagrange = [7,6,5,4,3,2,1,0]
        
        func_search = lzdict.search
        func_addEntry = lzdict.addEntry
        func_addEntryRange = lzdict.addEntryRange
        func_slideWindow = lzdict.slideWindow
        
        while src < dcsize:
            flag = 0
            flagpos = dest
            cbuffer[dest] = func_chr(flag)
            dest += 1
            
            for i in flagrange:
                match = func_search(data, src, dcsize)
                if match[1] > 0:
                    flag |= (1 << i)
                    
                    if match[1] <= 0x10:
                        cbuffer[dest] = func_chr((((match[1] - 1) & 0xF) << 4) | (((match[0] - 1) & 0xFFF) >> 8))
                        cbuffer[dest+1] = func_chr((match[0] - 1) & 0xFF)
                        dest += 2
                    elif match[1] <= 0x110:
                        cbuffer[dest] = func_chr(((match[1] - 17) & 0xFF) >> 4)
                        cbuffer[dest+1] = func_chr((((match[1] - 17) & 0xF) << 4) | (((match[0] - 1) & 0xFFF) >> 8))
                        cbuffer[dest+2] = func_chr((match[0] - 1) & 0xFF)
                        dest += 3
                    else:
                        cbuffer[dest] = func_chr((1 << 4) | (((match[1] - 273) & 0xFFFF) >> 12))
                        cbuffer[dest+1] = func_chr(((match[1] - 273) & 0xFFF) >> 4)
                        cbuffer[dest+2] = func_chr((((match[1] - 273) & 0xF) << 4) | (((match[0] - 1) & 0xFFF) >> 8))
                        cbuffer[dest+3] = func_chr((match[0] - 1) & 0xFF)
                        dest += 4
                    
                    func_addEntryRange(data, src, match[1])
                    func_slideWindow(match[1])
                    src += match[1]
                else:
                    cbuffer[dest] = data[src]
                    
                    func_addEntry(data, src)
                    func_slideWindow(1)
                    src += 1
                    dest += 1
                
                if src >= dcsize: break
            
            cbuffer[flagpos] = func_chr(flag)
        
        return cbuffer[0:dest]
    
class LzWindowDictionary():
    def __init__(self):
        self.offsetList = []
        for i in range(0x100):
            self.offsetList.append([])
        self.windowSize = 0x1000
        self.windowStart = 0
        self.windowLength = 0
        self.minMatchAmount = 3
        self.maxMatchAmount = 18
        self.blockSize = 0
    
    def search(self, data, offset, length):
        self.removeOldEntries(data[offset])
        
        minMatchAmount = self.minMatchAmount
        maxMatchAmount = self.maxMatchAmount
        windowlength = self.windowLength
        
        if offset < minMatchAmount or (length - offset) < minMatchAmount: return [0,0]
        
        match = [0,0]
        matchStart = 0
        matchSize = 0
        
        offsetListEntry = self.offsetList[data[offset]]
        i = len(offsetListEntry) - 1
        
        while i >= 0:
            matchStart = offsetListEntry[i]
            matchSize = 1
            
            while matchSize < maxMatchAmount and matchSize < windowlength and (matchStart + matchSize) < offset and (offset + matchSize) < length and data[offset+matchSize] == data[matchStart+matchSize]:
                matchSize += 1
            
            if matchSize >= minMatchAmount and matchSize > match[1]:
                match[0] = offset - matchStart
                match[1] = matchSize
                if matchSize == maxMatchAmount: break
            
            i -= 1
        
        return match
    
    def slideWindow(self, amount):
        if self.windowLength == self.windowSize:
            self.windowStart += amount
        else:
            if (self.windowLength + amount) <= self.windowSize:
                self.windowLength += amount
            else:
                amount -= (self.windowSize - self.windowLength)
                self.windowLength = self.windowSize
                self.windowStart += amount
    
    def removeOldEntries(self, index):
        offsetListEntry = self.offsetList[index]
        windowStart = self.windowStart
        i = 0
        
        func_len = len
        while i < func_len(offsetListEntry):
            if offsetListEntry[i] >= windowStart:
                break
            else:
                del offsetListEntry[0]
    
    def setWindowSize(self, size):
        self.windowSize = size
    
    def setMinMatchAmount(self, amount):
        self.minMatchAmount = amount
    
    def setMaxMatchAmount(self, amount):
        self.maxMatchAmount = amount
    
    def setBlockSize(self, size):
        self.blockSize = size
        self.windowLength = size
    
    def addEntry(self, data, offset):
        self.offsetList[data[offset]].append(offset)
    
    def addEntryRange(self, data, offset, length):
        i = 0
        offsetList = self.offsetList
        while i < length:
            offsetList[data[offset+i]].append(offset+i)
            i += 1
