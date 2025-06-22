import subprocess
import requests
from datetime import datetime
import time  # Import time module for sleep functionality
import re
# Telegram Bot credentials
telegram_token = '60'
telegram_chat_id = '-1'
THRESHOLD_GB = 100
# Log files and site URLs
log_files = {
    "d.ca": {
        "log_url": "https://a.ca/wp-content/plugins/automatic-email-testing-with-telegram-alerts/emaillog.txt",
        "site_url": "https://ca/wp-login.php" #uncached url to trigger php to run cron
    },
    "Lanare.ca": {
        "log_url": "https://la.ca/wp-content/plugins/automatic-email-testing-with-telegram-alerts/emaillog.txt",
        "site_url": "https://le.ca/yfplhu6/"
    },
    "BnCe.ca": {
        "log_url": "https://be.ca/wp-content/plugins/automatic-email-testing-with-telegram-alerts/emaillog.txt",
        "site_url": "https://bere.ca/wp-login.php"
    },
    "Herb.com": {
        "log_url": "https://h/wp-content/plugins/automatic-email-testing-with-telegram-alerts/emaillog.txt",
        "site_url": "https://hm/wp-login.php"
    },
    "Deek.com": {
        "log_url": "https://deom/wp-content/plugins/automatic-email-testing-with-telegram-alerts/emaillog.txt",
        "site_url": "https://d.com/wp-login.php"
    }
}
# Threshold Configuration
VMSTAT_THRESHOLDS = {
    "RUN_QUEUE": 8,         # r column (2 per core)
    "BLOCKED": 2,            # b column
    "SWAP_IN": 50,           # si column (kB/s)
    "SWAP_OUT": 50,          # so column (kB/s)
    "IO_WAIT": 15,           # wa column (percentage)
    "SYSTEM_CPU": 40,        # sy column (percentage)
    "FREE_MEM": 124288,      # 512MB (in kB)
    "SWAP_USED": 10          # % of swap used
}

# Function to send messages to Telegram
def send_telegram_message(token, chat_id, message):
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    data = {"chat_id": chat_id, "text": message}
    response = requests.post(url, data=data)
    if response.status_code == 200:
        print("Telegram message sent successfully.")
    else:
        print(f"Failed to send Telegram message. Status code: {response.status_code}, Response: {response.text}")

# Function to check if a service is active
def is_service_active(service_name):
    try:
        output = subprocess.check_output(['systemctl', 'is-active', service_name], stderr=subprocess.STDOUT)
        return output.strip().decode('utf-8') == 'active'
    except subprocess.CalledProcessError:
        return False

# Function to get the status of all services
def get_services_status():
    services = ["getdpd", "getdpd-service-monitor", "getdpdmonitor", "emaillog", "fail2ban", "monsy"]
    status = {}
    for service in services:
        status[service] = "✅up" if is_service_active(service) else "⚠🔴❌ down"
    return status

# Function to fetch and check log file status
def fetch_log_file(url):
    try:
        response = requests.get(url)
        if response.status_code == 200:
            return response.text.splitlines()
        else:
            print(f"Failed to fetch log file from {url}: {response.status_code}")
            return None
    except Exception as e:
        print(f"Error fetching log file from {url}: {e}")
        return None

def check_log_files(log_files):
    statuses = {}
    for site, info in log_files.items():
        # Navigate to the site URL
        site_url = info["site_url"]
        print(f"Accessing {site_url}...")

        # Perform a GET request to the site URL
        try:
            site_response = requests.get(site_url)
            http_status = site_response.status_code
            print(f"HTTP Status for {site_url}: {http_status}")  # Log the HTTP status

            time.sleep(5)  # Wait for 20 seconds between loading sites

            log_url = info["log_url"]
            lines = fetch_log_file(log_url)
            if lines is not None:
                if lines:
                    last_entry = lines[-1].strip()
                    # Extract the timestamp from the log entry
                    try:
                        last_timestamp_str = last_entry.split(']')[0][1:]  # Get the timestamp string
                        last_timestamp = datetime.strptime(last_timestamp_str, "%Y-%m-%d %H:%M:%S")  # Convert to datetime
                    except ValueError:
                        statuses[site] = "down (invalid timestamp format)"
                        continue

                    last_timestamp = last_timestamp.replace(tzinfo=None)

                    # Check if the log is older than 6 hours
                    if (datetime.utcnow() - last_timestamp).total_seconds() > 22320:
                        statuses[site] = "⚠🔴❌down (log older than 6 hours)"
                    elif "Failure" in last_entry:
                        statuses[site] = "⚠🔴❌down (email failure)"
                    else:
                        statuses[site] = "✅up"
                else:
                    statuses[site] = "⚠🔴❌down (log is empty)"
            else:
                statuses[site] = "⚠🔴❌down (fetch error)"
        except requests.exceptions.RequestException as e:
            statuses[site] = f"⚠🔴❌down (exception: {e})"

    return statuses

def get_system_usage():
    # Get CPU load average (first number only)
    cpu_load = subprocess.run(['uptime'], capture_output=True, text=True).stdout.strip()
    load_avg = cpu_load.split('load average: ')[1].split(',')[0]

    # Get used memory in MB
    mem_usage = subprocess.run(['free', '-m'], capture_output=True, text=True).stdout
    used_mem = [line.split()[2] for line in mem_usage.split('\n') if 'Mem:' in line][0]

    return f"CPU Load Average: {load_avg}\nUsed RAM: {used_mem} MB"

# Function to get disk space information
def get_disk_space():
    """Check available disk space on /dev/vda1 and return status message"""
    try:
        result = subprocess.run(['df', '-h', '/dev/vda1'], capture_output=True, text=True)
        lines = result.stdout.splitlines()
        if len(lines) < 2:
            return "⚠️ Disk check: Unexpected df output"

        columns = re.split(r'\s+', lines[1])
        avail_str = columns[3]

        if 'G' in avail_str:
            avail_gb = float(avail_str.replace('G', ''))
        elif 'T' in avail_str:
            avail_gb = float(avail_str.replace('T', '')) * 1024
        else:
            return "⚠️ Disk check: Unknown size format"

        if avail_gb < THRESHOLD_GB:
            return f"⚠️ WARNING: Only {avail_gb:.1f}GB left (threshold: {THRESHOLD_GB}GB)"
        else:
            return f"✅ Disk: {avail_gb:.1f}GB available"
    except Exception as e:
        return f"⚠️ Disk check error: {str(e)}"


# Function to get NGINX cache size
def get_nginx_cache_size():
    try:
        # Run sudo command to get cache directory size in blocks
        result = subprocess.run(
            ['sudo', 'du', '-s', '/var/run/nginx-cache'],
            capture_output=True,
            text=True,
            check=True
        )
        # Extract size in KB (first column of output)
        size_kb = int(result.stdout.split()[0])
        # Convert to MB with 3 decimal places
        size_mb = size_kb / 1024
        return f"NGINX Cache: {size_mb:.3f} MB"
    except subprocess.CalledProcessError as e:
        return f"⚠️ Cache Error: {e.stderr.strip() or 'Unknown error'}"
    except Exception as e:
        return f"⚠️ Cache Error: {str(e)}"


# Main function to check services and send status
def get_system_metrics():
    try:
        # Get CPU load
        cpu_load = subprocess.run(['uptime'], capture_output=True, text=True).stdout
        load_avg = cpu_load.split('load average: ')[1].split(',')[0].strip()

        # Get memory usage
        mem_info = subprocess.run(['free', '-m'], capture_output=True, text=True).stdout
        for line in mem_info.split('\n'):
            if 'Mem:' in line:
                parts = re.split(r'\s+', line.strip())
                mem_status = f"💾 RAM: {parts[2]}MB used/{parts[1]}MB"
                break
        else:
            mem_status = "💾 RAM: Error"

        # Get swap usage
        swap_info = subprocess.run(['free', '-m'], capture_output=True, text=True).stdout
        for line in swap_info.split('\n'):
            if 'Swap:' in line:
                parts = re.split(r'\s+', line.strip())
                if parts[1] == '0':  # No swap configured
                    swap_status = "🔁 Swap: None"
                else:
                    swap_used = int(parts[2])
                    swap_total = int(parts[1])
                    swap_pct = (swap_used / swap_total) * 100
                    status = "⚠️ " if swap_pct >= VMSTAT_THRESHOLDS['SWAP_USED'] else ""
                    swap_status = f"{status}🔁 Swap: {swap_used}MB/{swap_total}MB ({swap_pct:.1f}%)"
                break
        else:
            swap_status = "⚠️ Swap: Error"

        # Get vmstat metrics - FIXED I/O WAIT INDEX
        vmstat = subprocess.run(['vmstat', '1', '2'], capture_output=True, text=True).stdout
        if vmstat.count('\n') > 3:
            last_line = vmstat.strip().split('\n')[-1]
            parts = re.split(r'\s+', last_line.strip())
            if len(parts) > 15:
                # CORRECTED COLUMN INDEXES:
                # r  b   swpd   free   buff  cache   si   so    bi    bo   in   cs us sy id wa st
                # 0  1    2      3      4      5      6    7     8     9   10   11 12 13 14 15 16
                metrics = {
                    'r': parts[0],
                    'b': parts[1],
                    'si': parts[6],
                    'so': parts[7],
                    'wa': parts[15],  # I/O Wait is at index 15
                    'sy': parts[13],   # System CPU is at index 13
                    'free': int(parts[3]) // 1024  # Convert kB to MB
                }

                # Format with warnings
                r_status = "⚠️ " if int(metrics['r']) >= VMSTAT_THRESHOLDS['RUN_QUEUE'] else ""
                b_status = "⚠️ " if int(metrics['b']) >= VMSTAT_THRESHOLDS['BLOCKED'] else ""
                si_status = "⚠️ " if int(metrics['si']) >= VMSTAT_THRESHOLDS['SWAP_IN'] else ""
                so_status = "⚠️ " if int(metrics['so']) >= VMSTAT_THRESHOLDS['SWAP_OUT'] else ""
                wa_status = "⚠️ " if int(metrics['wa']) >= VMSTAT_THRESHOLDS['IO_WAIT'] else ""
                sy_status = "⚠️ " if int(metrics['sy']) >= VMSTAT_THRESHOLDS['SYSTEM_CPU'] else ""
                free_status = "⚠️ " if metrics['free'] < (VMSTAT_THRESHOLDS['FREE_MEM'] // 1024) else ""

                vmstat_status = (
                    f"📊 System Metrics:\n"
                    f"  {r_status}CPU Queue: {metrics['r']}\n"
                    f"  {b_status}Blocked: {metrics['b']}\n"
                    f"  {si_status}Swap In: {metrics['si']} kB/s\n"
                    f"  {so_status}Swap Out: {metrics['so']} kB/s\n"
                    f"  {wa_status}I/O Wait: {metrics['wa']}%\n"
                    f"  {sy_status}System CPU: {metrics['sy']}%\n"
                    f"  {free_status}Free RAM: {metrics['free']} MB"
                )
            else:
                vmstat_status = "⚠️ VMSTAT: Incomplete data"
        else:
            vmstat_status = "⚠️ VMSTAT: No data"

        return (
            f"⏱️  Load: {load_avg} (1 min)\n"
            f"{mem_status}\n"
            f"{swap_status}\n"
            f"{vmstat_status}"
        )

    except Exception as e:
        return f"⚠️ Metrics Error: {str(e)}"


def check_services():
    while True:  # Loop indefinitely
        cache_size = get_nginx_cache_size()  # Get NGINX cache size
        service_status = get_services_status()
        log_status = check_log_files(log_files)
        disk_status = get_disk_space()  # Get disk space info
        current_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        message = f"Status Report ({current_time}):\n"
        # Add system metrics
        message += "🔧 SYSTEM HEALTH\n"
        message += get_system_metrics() + "\n\n"

        message += "Service Statuses:\n"
        for service, state in service_status.items():
            message += f"{service}: {state}\n"

        message += "\nEmail Service Statuses:\n"
        for site, status in log_status.items():
            message += f"{site}: {status}\n"

        # Add system usage info
        system_usage = get_system_usage()
        message += f"\nSystem Usage:\n{system_usage}\n"

        # Add system usage and disk space info
        message += f"\nDisk Space:\n{disk_status}\n"  # Added disk space info
        message += f"\n{cache_size}\n"  # Add cache size information
        print(message)
        send_telegram_message(telegram_token, telegram_chat_id, message)

        break


if __name__ == "__main__":
    check_services()


