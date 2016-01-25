import subprocess as sp

FFMPEG_BIN = "ffmpeg"

'''
command = [ FFMPEG_BIN,
        '-y', # (optional) overwrite output file if it exists
        '-i', '1453542614.h264',
        '-i', 'parttwo.h264',
	'-c', 'copy',
	'-r', '24',
        'output.h264' ]
'''
command = ['ffmpeg', 
           '-y', 
           '-i', 'concat:1453546766.h264|parttwo.h264', 
           '-c', 'copy', 
           '-r', '24', 
           'output.h264']

pipe = sp.Popen( command, stdin=sp.PIPE, stderr=sp.PIPE)

