from subprocess import PIPE, Popen


def get_cpu_temperature():
    process = Popen(['vcgencmd', 'measure_temp'], stdout=PIPE)
    output, _error = process.communicate()
    return float(output[output.index(b"=") + 1:output.rindex(b"'")])

