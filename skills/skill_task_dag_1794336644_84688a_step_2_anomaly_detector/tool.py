import csv
from pathlib import Path

# Configuration
INPUT_CSV = r'C:\Users\derik\Desktop\Derik\Projects\Sentinel\workspaces\task_dag_1794336644_84688a_step_1_telemetry.csv'
OUTPUT_PATH = r'C:/Users/derik/Desktop/Derik/Projects/Sentinel/workspaces/task_dag_1794336644_84688a_step_2_anomaly_detector.py'

# Z-score threshold for anomaly detection
ZSCORE_THRESHOLD = 2.0


def load_telemetry_data(csv_path: str) -> list[dict]:
    """Load telemetry data from CSV file."""
    records = []
    with open(csv_path, 'r', newline='', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            records.append({
                'timestamp': row['timestamp'],
                'server_id': row['server_id'],
                'cpu_utilization': float(row['cpu_utilization']),
                'memory_mb': float(row['memory_mb']),
                'packet_loss_rate': float(row['packet_loss_rate'])
            })
    return records


def calculate_statistics(values: list[float]) -> dict:
    """Calculate mean and standard deviation for a list of values."""
    n = len(values)
    if n == 0:
        return {'mean': 0.0, 'std': 0.0}
    
    mean = sum(values) / n
    
    # Calculate standard deviation
    variance = sum((x - mean) ** 2 for x in values) / n
    std = variance ** 0.5
    
    return {'mean': mean, 'std': std}


def detect_anomalies(records: list[dict], stats_cpu: dict, stats_loss: dict) -> list[dict]:
    """Detect anomalies based on z-score threshold."""
    anomalies = []
    
    for record in records:
        cpu_zscore = (record['cpu_utilization'] - stats_cpu['mean']) / stats_cpu['std'] if stats_cpu['std'] > 0 else 0
        loss_zscore = (record['packet_loss_rate'] - stats_loss['mean']) / stats_loss['std'] if stats_loss['std'] > 0 else 0
        
        # Flag as anomaly if either metric exceeds z-score threshold
        is_anomaly = abs(cpu_zscore) > ZSCORE_THRESHOLD or abs(loss_zscore) > ZSCORE_THRESHOLD
        
        if is_anomaly:
            anomalies.append({
                'timestamp': record['timestamp'],
                'server_id': record['server_id'],
                'cpu_utilization': record['cpu_utilization'],
                'packet_loss_rate': record['packet_loss_rate'],
                'cpu_zscore': cpu_zscore,
                'loss_zscore': loss_zscore,
                'anomaly_type': 'CPU' if abs(cpu_zscore) > ZSCORE_THRESHOLD else 'PACKET_LOSS',
                'severity': 'HIGH' if abs(cpu_zscore) > 3.0 or abs(loss_zscore) > 3.0 else 'MEDIUM'
            })
    
    return anomalies


def generate_report(anomalies: list[dict]) -> str:
    """Generate anomaly breakdown report."""
    lines = [
        "=" * 60,
        "TELEMETRY ANOMALY DETECTION REPORT",
        "=" * 60,
        "",
        f"Total Records Analyzed: {len(anomalies)}",
        f"Anomaly Threshold (Z-Score): {ZSCORE_THRESHOLD}",
        ""
    ]
    
    if not anomalies:
        lines.append("No anomalies detected.")
        return "\n".join(lines)
    
    # Group by server
    servers = {}
    for anomaly in anomalies:
        sid = anomaly['server_id']
        if sid not in servers:
            servers[sid] = []
        servers[sid].append(anomaly)
    
    lines.extend([
        "ANOMALY BREAKDOWN BY SERVER:",
        "-" * 40,
        ""
    ])
    
    for server_id, server_anomalies in sorted(servers.items()):
        lines.append(f"Server: {server_id}")
        lines.append("-" * 20)
        
        # Sort by timestamp
        server_anomalies.sort(key=lambda x: x['timestamp'])
        
        for a in server_anomalies:
            lines.append(
                f"  [{a['timestamp']}] "
                f"CPU={a['cpu_utilization']:.2f} (z={a['cpu_zscore']:+.2f}) | "
                f"Loss={a['packet_loss_rate']:.4f} (z={a['loss_zscore']:+.2f}) | "
                f"Type={a['anomaly_type']} | Severity={a['severity']}"
            )
        
        lines.append("")
    
    # Summary statistics
    high_severity = sum(1 for a in anomalies if a['severity'] == 'HIGH')
    medium_severity = sum(1 for a in anomalies if a['severity'] == 'MEDIUM')
    
    lines.extend([
        "=" * 60,
        "SUMMARY STATISTICS",
        "=" * 60,
        f"Total Anomalies: {len(anomalies)}",
        f"High Severity: {high_severity}",
        f"Medium Severity: {medium_severity}",
        f"Affected Servers: {len(servers)}",
        ""
    ])
    
    return "\n".join(lines)


def main():
    """Main execution function."""
    try:
        # Load telemetry data
        print("Loading telemetry data...")
        records = load_telemetry_data(INPUT_CSV)
        print(f"Loaded {len(records)} records.")
        
        # Calculate statistics for each metric
        cpu_values = [r['cpu_utilization'] for r in records]
        loss_values = [r['packet_loss_rate'] for r in records]
        
        stats_cpu = calculate_statistics(cpu_values)
        stats_loss = calculate_statistics(loss_values)
        
        print(f"CPU Statistics - Mean: {stats_cpu['mean']:.2f}, Std: {stats_cpu['std']:.4f}")
        print(f"Packet Loss Statistics - Mean: {stats_loss['mean']:.4f}, Std: {stats_loss['std']:.4f}")
        
        # Detect anomalies
        print("Detecting anomalies...")
        anomalies = detect_anomalies(records, stats_cpu, stats_loss)
        
        # Generate and print report
        print("Generating anomaly report...")
        report = generate_report(anomalies)
        print(report)
        
    except FileNotFoundError as e:
        print(f"Error: Input file not found - {e}")
    except Exception as e:
        print(f"Error processing telemetry data: {e}")


if __name__ == "__main__":
    main()