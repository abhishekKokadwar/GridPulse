import { NextResponse } from 'next/server';

export const dynamic = 'force-dynamic';

export async function POST(request: Request) {
  try {
    const body = await request.json();
    const {
      type = 'PEAK_SHAVING',
      webhookUrl = process.env.ALERT_WEBHOOK_URL,
      peakKw = 885.5,
      thresholdKw = 800.0,
      overloadKw = 85.5,
      savings = 29925,
      actions = [],
    } = body;

    const targetUrl = webhookUrl || process.env.ALERT_WEBHOOK_URL;
    const nowTime = new Date().toLocaleTimeString();

    let slackPayload: any = {};

    if (type === 'PEAK_SHAVING') {
      const actionText = actions.length > 0
        ? actions.map((a: any) => `• *Tier ${a.tier} (${a.category}):* ${a.name} -> ${a.active_shed_kw} kW shed`).join('\n')
        : '• *Tier 1 (Soft Shedding):* Non-Critical Facilities & EV Setback -> 45.0 kW shed\n• *Tier 2 (Chiller Cycling):* Academic HVAC Duty Cycling -> 40.5 kW shed';

      slackPayload = {
        username: 'GridPulse AI Dispatcher',
        icon_emoji: ':battery:',
        attachments: [
          {
            color: overloadKw < 100 ? '#f59e0b' : '#ef4444',
            title: `IMPENDING PEAK DEMAND BREACH (+${overloadKw.toFixed(1)} kW)`,
            text: `*Automated Demand Response Triggered:*\nProjected campus peak is *${peakKw.toFixed(1)} kW*, breaching the contracted ceiling of *${thresholdKw.toFixed(1)} kW*.\n\n<http://localhost:3000|Open GridPulse Next.js Operations Portal>`,
            fields: [
              { title: 'Forecast Peak', value: `${peakKw.toFixed(1)} kW`, short: true },
              { title: 'Contract Threshold', value: `${thresholdKw.toFixed(1)} kW`, short: true },
              { title: 'Projected Overload', value: `+${overloadKw.toFixed(1)} kW`, short: true },
              { title: 'Potential Penalty Savings', value: `INR ${savings.toLocaleString()}`, short: true },
              { title: 'Active Countermeasures', value: actionText, short: false },
            ],
            footer: `GridPulse Real-Time Operations • Synced at ${nowTime}`,
            mrkdwn_in: ['text', 'fields'],
          },
        ],
      };
    } else {
      // SCADA Fault
      slackPayload = {
        username: 'GridPulse SCADA Watchdog',
        icon_emoji: ':rotating_light:',
        attachments: [
          {
            color: '#ef4444',
            title: 'SCADA Fault: CRITICAL VOLTAGE SAG [208.5V]',
            text: '*Grid Health Anomaly Detected:*\nSub-meter *M012* in building *BH2 (Hostels)* experienced nominal phase voltage drop below the 220V threshold.\n\n<http://localhost:3000|Open GridPulse SCADA Console>',
            fields: [
              { title: 'Meter ID', value: 'M012 (Smart Sub-Meter)', short: true },
              { title: 'Building Location', value: 'BH2 (Hostels)', short: true },
              { title: 'Observed Voltage', value: '208.50 V', short: true },
              { title: 'Standard Minimum', value: '220.00 V', short: true },
            ],
            footer: `GridPulse SCADA Watchdog • Synced at ${nowTime}`,
            mrkdwn_in: ['text', 'fields'],
          },
        ],
      };
    }

    if (!targetUrl || !targetUrl.startsWith('http')) {
      return NextResponse.json({
        success: true,
        status: 'SIMULATED_SUCCESS',
        statusCode: 200,
        message: 'Dispatched to Mock Console (No URL provided)',
        payload: slackPayload,
      });
    }

    // Live HTTP Dispatch to Slack
    const slackRes = await fetch(targetUrl, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(slackPayload),
    });

    return NextResponse.json({
      success: slackRes.ok,
      status: slackRes.ok ? 'SENT' : `FAILED_${slackRes.status}`,
      statusCode: slackRes.status,
      message: slackRes.ok ? 'Successfully delivered incident card to Slack.' : 'Slack delivery failed.',
      payload: slackPayload,
      timestamp: new Date().toISOString(),
    });
  } catch (error: any) {
    console.error('Webhook dispatch error:', error);
    return NextResponse.json({ success: false, error: error.message }, { status: 500 });
  }
}
