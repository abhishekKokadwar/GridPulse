import { NextResponse } from 'next/server';
import { query } from '@/lib/db';

export const dynamic = 'force-dynamic';

export async function GET() {
  try {
    const statsQuery = `
      SELECT 
        (SELECT COUNT(*) FROM buildings) AS building_count,
        (SELECT COUNT(*) FROM meters) AS meter_count,
        (SELECT COUNT(*) FROM energy_readings) AS readings_count,
        (SELECT COUNT(*) FROM alerts) AS alerts_count,
        (SELECT COUNT(*) FROM building_energy_aggregates) AS aggregates_count,
        (SELECT MAX(timestamp) FROM energy_readings) AS latest_reading_time;
    `;

    const recentQuery = `
      SELECT 
        ROUND(SUM(power_kw)::numeric, 1) as total_kw,
        ROUND(AVG(voltage_v)::numeric, 1) as avg_v,
        ROUND(AVG(power_factor)::numeric, 3) as avg_pf
      FROM energy_readings
      WHERE timestamp = (SELECT MAX(timestamp) FROM energy_readings);
    `;

    const [statsRows, recentRows] = await Promise.all([
      query(statsQuery),
      query(recentQuery),
    ]);

    const stats = statsRows[0] || {};
    const recent = recentRows[0] || {};

    return NextResponse.json({
      success: true,
      stats: {
        buildings: Number(stats.building_count || 0),
        meters: Number(stats.meter_count || 0),
        readings: Number(stats.readings_count || 0),
        alerts: Number(stats.alerts_count || 0),
        aggregates: Number(stats.aggregates_count || 0),
        latestReadingTime: stats.latest_reading_time,
      },
      instant: {
        instantaneousLoadKw: Number(recent.total_kw || 0),
        nominalVoltageV: Number(recent.avg_v || 230.0),
        powerFactorAvg: Number(recent.avg_pf || 0.92),
      },
      timestamp: new Date().toISOString(),
    });
  } catch (error: any) {
    console.error('Error fetching KPIs:', error);
    return NextResponse.json({ success: false, error: error.message }, { status: 500 });
  }
}
