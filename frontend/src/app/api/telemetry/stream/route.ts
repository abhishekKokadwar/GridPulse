import { NextResponse } from 'next/server';
import { query } from '@/lib/db';

export const dynamic = 'force-dynamic';

export async function GET(request: Request) {
  const { searchParams } = new URL(request.url);
  const limit = Math.min(parseInt(searchParams.get('limit') || '80', 10), 500);

  try {
    const rows = await query(`
      SELECT 
        a.id,
        a.window_start,
        a.window_end,
        a.building_id,
        b.building_name,
        b.category AS building_type,
        CAST(a.avg_power_kw AS FLOAT) AS avg_power_kw,
        CAST(a.avg_voltage_v AS FLOAT) AS avg_voltage_v,
        CAST(a.avg_power_factor AS FLOAT) AS avg_power_factor
      FROM building_energy_aggregates a
      LEFT JOIN buildings b ON a.building_id = b.building_id
      ORDER BY a.window_end DESC, a.id DESC
      LIMIT $1
    `, [limit]);

    // Aggregate by window_end for high-speed 60fps charting
    const timelineMap = new Map<string, { time: string; timestamp: string; totalPower: number; avgVoltage: number; count: number }>();

    for (const r of rows) {
      const rawIso = new Date(r.window_end).toISOString();
      const timeKey = new Date(r.window_end).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
      if (!timelineMap.has(timeKey)) {
        timelineMap.set(timeKey, { time: timeKey, timestamp: rawIso, totalPower: 0, avgVoltage: 0, count: 0 });
      }
      const entry = timelineMap.get(timeKey)!;
      entry.totalPower += Number(r.avg_power_kw) || 0;
      entry.avgVoltage += Number(r.avg_voltage_v) || 0;
      entry.count += 1;
    }

    const timeline = Array.from(timelineMap.values())
      .map(e => ({
        time: e.time,
        timestamp: e.timestamp,
        totalPower: Number(e.totalPower.toFixed(1)),
        avgVoltage: Number((e.avgVoltage / (e.count || 1)).toFixed(1)),
      }))
      .reverse();

    // Latest single window statistics
    const latestWindowEnd = rows.length > 0 ? rows[0].window_end : null;
    const latestWindowRows = latestWindowEnd ? rows.filter(r => r.window_end.toString() === latestWindowEnd.toString()) : [];
    const latestLoad = latestWindowRows.reduce((acc, curr) => acc + (Number(curr.avg_power_kw) || 0), 0);
    const latestVoltage = latestWindowRows.length > 0
      ? latestWindowRows.reduce((acc, curr) => acc + (Number(curr.avg_voltage_v) || 0), 0) / latestWindowRows.length
      : 230.0;

    return NextResponse.json({
      success: true,
      count: rows.length,
      latest: {
        windowEnd: latestWindowEnd,
        loadKw: Number(latestLoad.toFixed(1)),
        voltageV: Number(latestVoltage.toFixed(1)),
        activeBuildings: latestWindowRows.length,
      },
      timeline,
      rows,
      timestamp: new Date().toISOString(),
    });
  } catch (error: any) {
    console.error('Error fetching stream aggregates:', error);
    return NextResponse.json({ success: false, error: error.message }, { status: 500 });
  }
}
