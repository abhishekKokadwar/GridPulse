import { NextResponse } from 'next/server';
import { query } from '@/lib/db';

export const dynamic = 'force-dynamic';

export async function GET(request: Request) {
  const { searchParams } = new URL(request.url);
  const limit = Math.min(parseInt(searchParams.get('limit') || '120', 10), 500);

  try {
    // 1. High-speed timeline query: deduplicates (window_end, building_id) and sums across all buildings per window
    const timelineSql = `
      WITH recent_windows AS (
        SELECT window_end, building_id, avg_power_kw, avg_voltage_v, id
        FROM building_energy_aggregates
        WHERE window_end >= (SELECT MAX(window_end) - INTERVAL '40 minutes' FROM building_energy_aggregates)
      ),
      dedup AS (
        SELECT DISTINCT ON (window_end, building_id)
          window_end, avg_power_kw, avg_voltage_v
        FROM recent_windows
        ORDER BY window_end DESC, building_id, id DESC
      )
      SELECT 
        window_end,
        ROUND(SUM(avg_power_kw)::numeric, 1) as total_power_kw,
        ROUND(AVG(avg_voltage_v)::numeric, 1) as avg_voltage_v,
        COUNT(*) as active_buildings
      FROM dedup
      GROUP BY window_end
      ORDER BY window_end ASC
      LIMIT 40;
    `;

    // 2. Latest deduplicated building rows for building cards and table
    const rowsSql = `
      WITH latest_buildings AS (
        SELECT DISTINCT ON (a.building_id)
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
        ORDER BY a.building_id, a.window_end DESC, a.id DESC
      )
      SELECT * FROM latest_buildings
      ORDER BY avg_power_kw DESC;
    `;

    const [timelineRows, buildingRows] = await Promise.all([
      query(timelineSql),
      query(rowsSql),
    ]);

    // Format timeline points for 60fps chart
    const timeline = timelineRows.map((r: any) => {
      const d = new Date(r.window_end);
      return {
        time: d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false }),
        timestamp: d.toISOString(),
        totalPower: Number(r.total_power_kw) || 0,
        avgVoltage: Number(r.avg_voltage_v) || 230.0,
      };
    });

    const latestWindowEnd = timelineRows.length > 0 ? timelineRows[timelineRows.length - 1].window_end : null;
    const latestLoad = buildingRows.reduce((acc: number, curr: any) => acc + (Number(curr.avg_power_kw) || 0), 0);
    const latestVoltage = buildingRows.length > 0
      ? buildingRows.reduce((acc: number, curr: any) => acc + (Number(curr.avg_voltage_v) || 0), 0) / buildingRows.length
      : 231.8;

    return NextResponse.json({
      success: true,
      count: buildingRows.length,
      latest: {
        windowEnd: latestWindowEnd,
        loadKw: Number(latestLoad.toFixed(1)),
        voltageV: Number(latestVoltage.toFixed(1)),
        activeBuildings: buildingRows.length,
      },
      timeline,
      rows: buildingRows,
      timestamp: new Date().toISOString(),
    });
  } catch (error: any) {
    console.error('Error fetching stream aggregates:', error);
    return NextResponse.json({ success: false, error: error.message }, { status: 500 });
  }
}
