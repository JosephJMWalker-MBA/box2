<?php
declare(strict_types=1);
require dirname(__DIR__).'/app/bootstrap.php';
$directory=sys_get_temp_dir().'/box2-capture-upgrade-'.bin2hex(random_bytes(6));mkdir($directory,0700,true);
config(['storage_path'=>$directory,'secret'=>str_repeat('u',64),'environment'=>'local']);$_SESSION=['admin'=>true,'last_active'=>time()];
db()->exec('CREATE TABLE schema_migrations(version TEXT PRIMARY KEY,applied_at TEXT NOT NULL)');
foreach(['001.sql','002.sql'] as $file) {db()->exec(file_get_contents(dirname(__DIR__).'/migrations/'.$file));query('INSERT INTO schema_migrations VALUES (?,?)',[$file,utc()]);}
$night=schedule_night('2030-10-11');$slot=query("SELECT id FROM slots WHERE show_night_id=? AND visibility='private' ORDER BY start_at_utc LIMIT 1",[$night])->fetchColumn();
$id=bin2hex(random_bytes(12));
query("INSERT INTO bookings(id,slot_id,stage_name,email,performance_type,consent_level,livestream_allowed,archive_allowed,clips_allowed,terms_version,consented_at,orientation_version,status,created_at,updated_at) VALUES (?,?,?,?,'standup','private',0,0,0,?,?,?,'checked_in',?,?)",[$id,$slot,'Synthetic private old guest','synthetic@example.test','2026-10-09',utc(),'2026-10-09',utc(),utc()]);
query('INSERT INTO booking_allocations(booking_id,slot_id) VALUES (?,?)',[$id,$slot]);query("UPDATE show_nights SET recording_mode='confirmed_off',recording_confirmed_at=? WHERE id=?",[utc(),$night]);
migrate();migrate();$state=query('SELECT * FROM show_nights WHERE id=?',[$night])->fetch();
if ($state['broadcast_source']!=='unknown'||$state['room_transmission']!=='unknown'||$state['room_recording']!=='unknown'||$state['private_room_occupied']!==1||private_capture_safe($state)) throw new RuntimeException('Unsafe legacy confirmation migration.');
if ((int)query('SELECT count(*) FROM editorial_grants')->fetchColumn()!==0 || config()['allow_house_continuity'] || config()['allow_bookings'] || config()['venue_public_enabled']) throw new RuntimeException('Migration enabled a permission.');
if (booking_record($id)['orientation_version']!=='2026-10-09') throw new RuntimeException('Legacy acknowledgment changed.');
try {set_recording_mode($night,'public');throw new LogicException('Stage resumed.');} catch (InvalidArgumentException $exception) {}
echo "PASS migration retains legacy records, preserves private occupancy, makes capture unverified, grants no new rights, and leaves launch/house gates disabled\n";
