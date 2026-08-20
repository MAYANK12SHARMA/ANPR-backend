from datetime import datetime
from html import escape


def build_completion_email(
    recipient_name: str,
    job_id: str,
    total_vehicles: int,
    total_plates: int,
    total_pedestrians: int,
    total_alerts: int,
    processing_time: str,
    dashboard_url: str | None = None,
) -> str:
    """
    Build HTML email sent after a video processing job completes.
    """

    recipient_name = escape(recipient_name)
    job_id = escape(job_id)
    processing_time = escape(processing_time)

    generated_time = datetime.now()

    completed_time = generated_time.strftime("%d %b %Y %I:%M %p")

    current_year = generated_time.year

    if dashboard_url:
        dashboard_button = f"""
        <div style="text-align:center;margin-top:35px;">
            <a
                href="{dashboard_url}"
                style="
                    background:#2563eb;
                    color:#ffffff;
                    text-decoration:none;
                    padding:14px 30px;
                    border-radius:10px;
                    font-size:15px;
                    font-weight:bold;
                    display:inline-block;
                "
            >
                🔗 View Processing Report
            </a>
        </div>
        """

        dashboard_message = """
        <li>
            Visit the dashboard to review processed videos,
            analytics and downloadable reports.
        </li>
        """

    else:
        dashboard_button = ""
        dashboard_message = ""

    if total_alerts == 0:
        attachment_message = """
        No alert snapshots were generated because no incidents
        requiring alerts were detected during processing.
        """
    else:
        attachment_message = f"""
        <b>{total_alerts}</b> alert snapshot(s) generated during
        video processing have been attached to this email.
        """

    return f"""
<!DOCTYPE html>

<html>

<head>

<meta charset="UTF-8">

<meta
    name="viewport"
    content="width=device-width, initial-scale=1.0"
/>

<title>Processing Completed - {job_id}</title>

</head>

<body
style="
    margin:0;
    padding:30px;
    background:#eef2f7;
    font-family:Arial, Helvetica, sans-serif;
"
>

<table
align="center"
width="700"
cellpadding="0"
cellspacing="0"
style="
    background:white;
    border-radius:16px;
    overflow:hidden;
    box-shadow:0 10px 35px rgba(0,0,0,.08);
"
>

<tr>

<td
style="
    background:#111827;
    text-align:center;
    padding:40px;
"
>

<div
style="
    font-size:42px;
"
>

🚦

</div>

<h1
style="
    color:white;
    margin:15px 0 5px;
    font-size:30px;
"
>

Traffic Surveillance Intelligence System

</h1>

<p
style="
    color:#d1d5db;
    font-size:15px;
    margin:0;
"
>

Video Processing Completed Successfully

</p>

<div
style="
    display:inline-block;
    margin-top:20px;
    background:#16a34a;
    color:white;
    padding:8px 18px;
    border-radius:30px;
    font-size:13px;
    font-weight:bold;
"
>

PROCESSING COMPLETED

</div>

</td>

</tr>

<tr>

<td style="padding:40px;">

<h2
style="
    margin-top:0;
    color:#111827;
"
>

Hello {recipient_name},

</h2>

<p
style="
    font-size:16px;
    line-height:28px;
    color:#4b5563;
"
>

Your video processing request has completed successfully.

The analysis summary and generated alert snapshots
are provided below.

</p>

</td>

</tr>

<tr>

<td style="padding:0 40px;">

<table
width="100%"
style="
    background:#f8fafc;
    border-radius:12px;
    padding:22px;
"
>

<tr>

<td colspan="2">

<h2
style="
    margin-top:0;
    color:#111827;
"
>

📹 Processing Summary

</h2>

</td>

</tr>
<tr>

<td style="padding:10px 0;">
<b>Job ID</b>
</td>

<td>
{job_id}
</td>

</tr>

<tr>

<td style="padding:10px 0;">
<b>Status</b>
</td>

<td>

<span
style="
    background:#dcfce7;
    color:#15803d;
    padding:6px 14px;
    border-radius:30px;
    font-weight:bold;
"
>

Completed

</span>

</td>

</tr>

<tr>

<td style="padding:10px 0;">
<b>Processing Result</b>
</td>

<td>

Analysis completed successfully.

</td>

</tr>

<tr>

<td style="padding:10px 0;">
<b>Completed At</b>
</td>

<td>

{completed_time}

</td>

</tr>

<tr>

<td style="padding:10px 0;">
<b>Processing Time</b>
</td>

<td>

{processing_time}

</td>

</tr>

<tr>

<td style="padding:10px 0;">
<b>Email Generated</b>
</td>

<td>

{completed_time}

</td>

</tr>

</table>

</td>

</tr>

<tr>

<td style="padding:40px;">

<h2
style="
    margin-top:0;
    color:#111827;
"
>

📊 Analysis Summary

</h2>

<table
width="100%"
cellpadding="15"
style="
    border-collapse:separate;
    border-spacing:18px;
"
>

<tr>

<td
style="
    background:#eff6ff;
    border-radius:14px;
    text-align:center;
    width:50%;
    border:1px solid #dbeafe;
"
>

<div style="font-size:38px;">

🚗

</div>

<h1
style="
    margin:10px 0 5px;
    color:#1e3a8a;
"
>

{total_vehicles}

</h1>

<div
style="
    color:#475569;
    font-size:15px;
    font-weight:bold;
"
>

Vehicles Detected

</div>

</td>

<td
style="
    background:#ecfeff;
    border-radius:14px;
    text-align:center;
    width:50%;
    border:1px solid #cffafe;
"
>

<div style="font-size:38px;">

🔖

</div>

<h1
style="
    margin:10px 0 5px;
    color:#155e75;
"
>

{total_plates}

</h1>

<div
style="
    color:#475569;
    font-size:15px;
    font-weight:bold;
"
>

Number Plates

</div>

</td>

</tr>

<tr>

<td
style="
    background:#fefce8;
    border-radius:14px;
    text-align:center;
    border:1px solid #fde68a;
"
>

<div style="font-size:38px;">

🚶

</div>

<h1
style="
    margin:10px 0 5px;
    color:#854d0e;
"
>

{total_pedestrians}

</h1>

<div
style="
    color:#475569;
    font-size:15px;
    font-weight:bold;
"
>

Pedestrian Alerts

</div>

</td>

<td
style="
    background:#fef2f2;
    border-radius:14px;
    text-align:center;
    border:1px solid #fecaca;
"
>

<div style="font-size:38px;">

🚨

</div>

<h1
style="
    margin:10px 0 5px;
    color:#991b1b;
"
>

{total_alerts}

</h1>

<div
style="
    color:#475569;
    font-size:15px;
    font-weight:bold;
"
>

Total Alerts

</div>

</td>

</tr>

</table>

</td>

</tr>

<tr>

<td style="padding:0 40px;">

<div
style="
    background:#ffffff;
    border:1px solid #e5e7eb;
    border-radius:12px;
    overflow:hidden;
"
>

<table
width="100%"
cellpadding="14"
style="
    border-collapse:collapse;
"
>

<tr
style="
    background:#f3f4f6;
"
>

<th align="left">

Metric

</th>

<th align="right">

Count

</th>

</tr>

<tr>

<td>

🚗 Vehicles Detected

</td>

<td align="right">

<b>{total_vehicles}</b>

</td>

</tr>

<tr>

<td>

🔖 Number Plates

</td>

<td align="right">

<b>{total_plates}</b>

</td>

</tr>

<tr>

<td>

🚶 Pedestrian Alerts

</td>

<td align="right">

<b>{total_pedestrians}</b>

</td>

</tr>

<tr>

<td>

🚨 Total Alerts

</td>

<td align="right">

<b>{total_alerts}</b>

</td>

</tr>

</table>

</div>

</td>

</tr>
<tr>

<td
style="
    padding:40px;
"
>

<div
style="
    background:#fff7ed;
    border-left:6px solid #f97316;
    border-radius:12px;
    padding:25px;
"
>

<h2
style="
    margin-top:0;
    color:#9a3412;
"
>

📷 Alert Snapshots

</h2>

<p
style="
    color:#444;
    line-height:28px;
    margin-bottom:10px;
"
>

{attachment_message}

</p>

<p
style="
    color:#6b7280;
    margin:0;
"
>

You can download and review every attached snapshot
to verify incidents detected during processing.

</p>

</div>

</td>

</tr>

<tr>

<td>

{dashboard_button}

</td>

</tr>

<tr>

<td
style="
padding:0 40px 40px 40px;
"
>

<div
style="
background:#f8fafc;
border-radius:12px;
padding:25px;
border:1px solid #e5e7eb;
"
>

<h3
style="
margin-top:0;
color:#111827;
"
>

ℹ️ Important Information

</h3>

<ul
style="
margin:0;
padding-left:20px;
color:#4b5563;
line-height:28px;
"
>

<li>

This email was automatically generated after the
processing pipeline completed successfully.

</li>

<li>

All generated alert snapshots have been attached
with this email whenever alerts were detected.

</li>

<li>

If multiple alerts were detected, please review
each attachment carefully.

</li>

{dashboard_message}

</ul>

</div>

</td>

</tr>

<tr>

<td
style="
padding:0 40px 35px 40px;
"
>

<div
style="
background:#eff6ff;
border-left:5px solid #2563eb;
border-radius:12px;
padding:20px;
"
>

<h3
style="
margin-top:0;
color:#1e3a8a;
"
>

📬 Need Assistance?

</h3>

<p
style="
margin:0;
color:#475569;
line-height:28px;
"
>

If you encounter any issue while reviewing the
processing results, please contact your system
administrator for assistance.

</p>

</div>

</td>

</tr>
<tr>

<td
style="
padding:40px;
text-align:center;
background:#111827;
"
>

<div
style="
font-size:34px;
margin-bottom:10px;
"
>

🚦

</div>

<h2
style="
margin:0;
color:white;
font-size:22px;
"
>

Traffic Surveillance Intelligence System

</h2>

<p
style="
margin-top:15px;
font-size:14px;
color:#d1d5db;
line-height:26px;
"
>

AI Powered Vehicle Detection •
Automatic Number Plate Recognition •
Pedestrian Analytics •
Intelligent Alert Generation

</p>

<hr
style="
margin:30px 0;
border:none;
border-top:1px solid #374151;
"
>

<p
style="
margin:0;
font-size:13px;
color:#9ca3af;
"
>

This is an automatically generated email.

Please do not reply to this email.

</p>

<p
style="
margin-top:12px;
font-size:13px;
color:#9ca3af;
"
>

© {current_year} Traffic Surveillance Intelligence System

</p>

</td>

</tr>

</table>

</body>

</html>
"""
