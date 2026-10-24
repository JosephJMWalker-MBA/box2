<?php
declare(strict_types=1);
require dirname(__DIR__).'/app/bootstrap.php';
$directory=sys_get_temp_dir().'/box2-upgrade-'.bin2hex(random_bytes(6));mkdir($directory,0700,true);
config(['storage_path'=>$directory,'secret'=>str_repeat('m',64),'environment'=>'local']);
$checks=0;
function upgrade_check(bool $ok,string $label): void {global $checks;if(!$ok) throw new RuntimeException('FAIL: '.$label);$checks++;echo "PASS {$label}\n";}
db()->exec('CREATE TABLE schema_migrations(version TEXT PRIMARY KEY,applied_at TEXT NOT NULL)');
db()->exec(file_get_contents(dirname(__DIR__).'/migrations/001.sql'));
query('INSERT INTO schema_migrations VALUES (?,?)',['001.sql',utc()]);
$night=schedule_night('2030-01-11');$slots=query('SELECT * FROM slots WHERE show_night_id=? ORDER BY start_at_utc',[$night])->fetchAll();
$ids=[bin2hex(random_bytes(12)),bin2hex(random_bytes(12)),bin2hex(random_bytes(12))];
foreach($ids as $index=>$id) {
    query('INSERT INTO bookings(id,slot_id,stage_name,email,performance_type,consent_level,livestream_allowed,archive_allowed,clips_allowed,terms_version,consented_at,orientation_version,status,created_at,updated_at)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',[$id,$slots[$index===2?0:$index]['id'],'Synthetic Legacy','legacy@example.test','standup','live_only',1,0,0,'2026-10-08',utc(),'2026-10-08',$index===2?'cancelled':'booked',utc(),utc()]);
}
$links=issue_booking_links($ids[0],$slots[0]['start_at_utc']);
$oldBody="Five-minute set in a ten-minute allocation.\nCheck in: Fri Jan 11, 8:40 PM EST\nConfirm: {$links['confirm']}\nCancel: {$links['cancel']}\n";
$payload=json_encode(['subject'=>'Synthetic legacy reminder','body'=>$oldBody]);
foreach(['confirmation'=>'accepted','day_of'=>'disabled','two_hours'=>'pending','check_in_30'=>'failed','stage_10'=>'sending'] as $type=>$status) {
    query('INSERT INTO reminders(booking_id,type,due_at_utc,sent_at,attempt_count,status,claim_id,claimed_at,payload) VALUES (?,?,?,?,?,?,?,?,?)',
        [$ids[0],$type,'2030-01-11T19:00:00Z',$status==='accepted'?utc():null,1,$status,$status==='sending'?'original-claim':null,$status==='sending'?utc():null,$payload]);
}
query("INSERT INTO reminders(booking_id,type,due_at_utc,status,payload) VALUES (?,'confirmation',?,'uncertain',?)",[$ids[1],'2030-01-11T19:00:00Z',$payload]);
$tokens=query('SELECT * FROM booking_tokens ORDER BY id')->fetchAll();
$before=query('SELECT * FROM reminders ORDER BY id')->fetchAll();
migrate();migrate();
upgrade_check((int)query('SELECT count(*) FROM bookings')->fetchColumn()===3,'existing booking rows preserved');
foreach($ids as $id) {
    $booking=booking_record($id);
    upgrade_check($booking['duration_minutes']===5 && $booking['block_count']===1,'legacy booking backfilled to one five-minute set');
    upgrade_check($booking['orientation_version']==='2026-10-08' && $booking['terms_version']==='2026-10-08','migration does not invent new consent acknowledgments');
}
upgrade_check((int)query('SELECT count(*) FROM booking_allocations WHERE active=1')->fetchColumn()===2,'only uncancelled legacy bookings reserve allocations');
upgrade_check((int)query('SELECT active FROM booking_allocations WHERE booking_id=?',[$ids[2]])->fetchColumn()===0,'cancelled legacy allocation retained as inactive history');
upgrade_check(query('SELECT * FROM booking_tokens ORDER BY id')->fetchAll()===$tokens,'hashed signed-link tokens and expiry are untouched');
$after=query('SELECT * FROM reminders ORDER BY id')->fetchAll();
upgrade_check(count($before)===count($after),'migration does not enqueue duplicate reminders');
foreach($after as $index=>$row) {
    foreach(['id','due_at_utc','sent_at','attempt_count','status','claim_id','claimed_at'] as $key) {
        upgrade_check($row[$key]===$before[$index][$key],'existing '.$row['type'].' '.$key.' is preserved');
    }
    $body=json_decode($row['payload'],true);
    if(in_array($row['status'],['accepted','sending','uncertain'],true)) {
        upgrade_check($row['payload']===$before[$index]['payload'],'accepted/claimed/uncertain payload not rewritten or replayed');
    } else {
        upgrade_check($body['links']===$links,'unsent payload retains original confirm/cancel authorization');
        upgrade_check($body['policy_version']===BOX2_TERMS && str_contains($body['body'],'Arrival window:') && str_contains($body['body'],'Check in immediately upon arrival') && str_contains($body['body'],'On deck at:') && !str_contains($body['body'],'Check in:'),'unsent legacy reminder now describes the approved arrival window');
    }
}
query("UPDATE bookings SET status='cancelled' WHERE id=?",[$ids[0]]);
upgrade_check((int)query('SELECT count(*) FROM booking_allocations WHERE booking_id=? AND active=1',[$ids[0]])->fetchColumn()===0,'database cancellation trigger releases a migrated reservation');
upgrade_check(query('PRAGMA integrity_check')->fetchColumn()==='ok','upgrade integrity');
upgrade_check(config()['allow_bookings']===false && config()['venue_public_enabled']===false,'upgrade leaves launch permission gates disabled');
echo "{$checks} migration/outbox checks passed.\n";
