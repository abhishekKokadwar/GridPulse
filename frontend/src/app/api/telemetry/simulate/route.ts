import { NextResponse } from 'next/server';
import { query } from '@/lib/db';

export const dynamic = 'force-dynamic';

export async function POST(request: Request) {
  try {
    const now = new Date();
    const windowStart = new Date(now.getTime() - 5 * 60 * 1000);

    // Fetch buildings
    const buildings = await query('SELECT building_id, building_name, category FROM buildings');
    
    if (!buildings || buildings.length === 0) {
      return NextResponse.json({ success: false, error: 'No buildings found in database' }, { status: 404 });
    }

    // Generate live aggregate rows for all 22 buildings matching exact schema
    const aggregateValues: string[] = [];
    for (const b of buildings) {
      const isLarge = b.category === 'Departments' || b.category === 'Lecture Theatres';
      const baseLoad = isLarge ? 32.0 : 18.0;
      const load = Number((baseLoad + (Math.random() - 0.45) * 14.0).toFixed(2));
      const voltage = Number((415.0 + (Math.random() - 0.5) * 3.5).toFixed(2));
      const pf = Number((0.925 + Math.random() * 0.05).toFixed(3));
      
      aggregateValues.push(`('${windowStart.toISOString()}', '${now.toISOString()}', '${b.building_id}', ${load}, ${voltage}, ${pf})`);
    }

    const insertSql = `
      INSERT INTO building_energy_aggregates 
        (window_start, window_end, building_id, avg_power_kw, avg_voltage_v, avg_power_factor)
      VALUES ${aggregateValues.join(',\n')};
    `;

    await query(insertSql);

    return NextResponse.json({
      success: true,
      message: `Ingested live telemetry batch for all ${buildings.length} facilities into Neon Cloud DB!`,
      timestamp: now.toISOString(),
      buildingsUpdated: buildings.length,
    });
  } catch (error: any) {
    console.error('Error simulating live batch:', error);
    return NextResponse.json({ success: false, error: error.message }, { status: 500 });
  }
}
