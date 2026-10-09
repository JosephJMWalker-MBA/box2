<?php
declare(strict_types=1);

require dirname(__DIR__).'/app/bootstrap.php';
$directory=sys_get_temp_dir().'/box2-tests-'.bin2hex(random_bytes(6));
mkdir($directory,0700,true);
config(['storage_path'=>$directory,'secret'=>str_repeat('x',64),'environment'=>'local',
    'allow_bookings'=>true,'venue_public_enabled'=>true,'mail_transport'=>'disabled',
    'admin_password_hash'=>password_hash('synthetic-test-password',PASSWORD_DEFAULT)]);
$_SERVER['REMOTE_ADDR']='127.0.0.1';
$_SESSION=[];
migrate();migrate();
$checks=0;
function check(bool $condition,string $label): void {global $checks;if (!$condition) throw new RuntimeException('FAIL: '.$label);$checks++;echo "PASS {$label}\n";}
function denied(callable $work,string $label): void {try {$work();} catch (Throwable $e) {check(true,$label);return;}check(false,$label);}
function payload(int $slot): array {return ['slot_id'=>$slot,'stage_name'=>'Synthetic Comic','email'=>'synthetic@example.test',
    'performance_type'=>'standup','orientation_agreed'=>'1','terms_agreed'=>'1','livestream_allowed'=>'1','archive_allowed'=>'1','clips_allowed'=>'1'];}

generate_schedule('2030-01-06',7);
check((int)query('SELECT count(*) FROM show_nights')->fetchColumn()===6,'six nights, Tuesday excluded');
foreach (query('SELECT id FROM show_nights')->fetchAll() as $night) {
    check(count(availability((int)$night['id']))===30,'regular night has 30 actual blocks');
    check((int)query("SELECT count(*) FROM slots WHERE show_night_id=? AND visibility='public'",[$night['id']])->fetchColumn()===22,'22 public blocks');
}
$night=(int)query("SELECT id FROM show_nights WHERE show_date='2030-01-11'")->fetchColumn();
$slots=availability($night);
check($slots[0]['start_at_utc']==='2030-01-12T02:00:00Z','9 PM winter UTC mapping');
check($slots[29]['start_at_utc']==='2030-01-12T06:50:00Z','1:50 AM belongs to next calendar day');
$summer=schedule_night('2030-07-12');
check(availability($summer)[0]['start_at_utc']==='2030-07-13T01:00:00Z','summer DST UTC mapping');
$fall=schedule_night('2030-11-02');
$fallSlots=availability($fall);
check(count($fallSlots)===36,'fall-back retains 36 unique actual blocks');
check(count(array_unique(array_column($fallSlots,'start_at_utc')))===36,'repeated local hour has immutable distinct instants');
check(str_contains(local_label('2030-11-03T05:20:00Z'),'EDT') && str_contains(local_label('2030-11-03T06:20:00Z'),'EST'),'repeated hour is labelled by timezone offset');
denied(fn()=>local_instant('2027-03-14','02:00'),'nonexistent spring endpoint rejected');
denied(fn()=>local_instant('2030-11-03','01:30'),'ambiguous endpoint rejected');
generate_schedule('2027-03-13',1);
check(query("SELECT status FROM show_nights WHERE show_date='2027-03-13'")->fetchColumn()==='closed','invalid DST show closes for host resolution');
$_SESSION['admin']=true;$_SESSION['last_active']=time();
override_night($night,['status'=>'closed','start'=>'21:00','end'=>'02:00','override_note'=>'Synthetic outside gig','guest_host'=>'Test Host']);
generate_schedule('2030-01-11',1);
check(query('SELECT status FROM show_nights WHERE id=?',[$night])->fetchColumn()==='closed','generation preserves host override');
denied(fn()=>create_booking(payload((int)$slots[0]['id'])),'closed nights cannot be booked');
override_night($night,['status'=>'open','start'=>'21:00','end'=>'02:00']);
$booking=create_booking(payload((int)$slots[0]['id']));
$id=$booking['booking']['id'];
check(booking_record($id)['status']==='booked','booking writes through complete transaction');
check(!db()->inTransaction(),'booking transaction closed');
denied(fn()=>create_booking(payload((int)$slots[0]['id'])),'duplicate slot rejected');
check(count(query('SELECT * FROM bookings')->fetchAll())===1,'failed collision leaves no partial rows');
$bad=payload((int)$slots[1]['id']);$bad['email']='broken';denied(fn()=>create_booking($bad),'invalid email rejected');
$bad=payload((int)$slots[1]['id']);$bad['teleprompter_text']=str_repeat('a',5001);denied(fn()=>create_booking($bad),'oversize script rejected');
$bad=payload((int)$slots[1]['id']);unset($bad['orientation_agreed']);denied(fn()=>create_booking($bad),'orientation required server-side');
denied(fn()=>create_booking(payload((int)$slots[23]['id'])),'held blocks cannot be booked');
denied(fn()=>consent(['clips_allowed'=>'1','livestream_allowed'=>'1']),'clip permission requires recording');
parse_str(parse_url($booking['links']['confirm'],PHP_URL_QUERY),$confirm);
$forged=$confirm;$forged['signature']=str_repeat('0',64);denied(fn()=>authorized_token($forged),'forged signed link rejected');
check(authorized_token($confirm)['booking_id']===$id,'valid signed link authorizes only its booking');
check(apply_booking_link($confirm)['status']==='confirmed','confirmation works');
denied(fn()=>apply_booking_link($confirm),'used token cannot be replayed');
parse_str(parse_url($booking['links']['cancel'],PHP_URL_QUERY),$cancel);
check(apply_booking_link($cancel)['status']==='cancelled','cancellation works');
check(availability($night)[0]['state']==='available','cancelled slot reopens');
denied(fn()=>apply_booking_link($cancel),'cancellation cannot be replayed');
$booking=create_booking(payload((int)$slots[0]['id']));
parse_str(parse_url($booking['links']['confirm'],PHP_URL_QUERY),$expired);
query('UPDATE booking_tokens SET expires_at=? WHERE booking_id=?',['2000-01-01T00:00:00Z',$booking['booking']['id']]);
denied(fn()=>authorized_token($expired),'expired booking link rejected');
denied(fn()=>transaction(function (): void {query("UPDATE slots SET status='closed' WHERE id=1");throw new RuntimeException('synthetic');}),'transaction rolls back exception');
check(query('SELECT status FROM slots WHERE id=1')->fetchColumn()==='open','rollback restores write');
$private=payload((int)$slots[28]['id']);unset($private['livestream_allowed'],$private['archive_allowed'],$private['clips_allowed']);
$p=create_booking($private)['booking'];
denied(fn()=>host_booking_action($p['id'],'checked_in'),'private check-in blocked with unknown recording state');
set_recording_mode($night,'confirmed_off');host_booking_action($p['id'],'checked_in');
denied(fn()=>set_recording_mode($night,'public'),'public broadcast cannot resume during checked-in private set');
denied(fn()=>host_booking_action($p['id'],'highlight'),'private set cannot be a highlight candidate');
host_booking_action($p['id'],'performed');set_recording_mode($night,'public');
$live=payload((int)$slots[1]['id']);unset($live['archive_allowed'],$live['clips_allowed']);
$l=create_booking($live)['booking'];denied(fn()=>host_booking_action($l['id'],'clip_this'),'live-only set cannot be clipped');
$_SESSION=[];denied(fn()=>host_booking_action($l['id'],'checked_in'),'privileged action denied without auth');
denied(fn()=>verify_csrf([]),'missing CSRF denied');
denied(fn()=>verify_csrf(['csrf'=>str_repeat('0',64)]),'wrong CSRF denied');
verify_csrf(['csrf'=>csrf()]);check(true,'valid CSRF accepted');
for($i=0;$i<3;$i++) throttle('synthetic',3);
denied(fn()=>throttle('synthetic',3),'request spam throttled');
$writer=submit_writer(['text'=>'<script>alert(1)</script>','alias'=>'Synthetic Writer','terms_agreed'=>'1']);
$w=query('SELECT * FROM writer_submissions WHERE id=?',[$writer['id']])->fetch();
check($w['perform_allowed']===0 && $w['publish_allowed']===0 && $w['ai_allowed']===0 && $w['music_allowed']===0,'writer grants default off');
check(!str_contains(e($w['text']),'<script>'),'writer text is output escaped');
parse_str(parse_url($writer['withdrawal'],PHP_URL_QUERY),$withdraw);withdraw_writer($withdraw['token']);
denied(fn()=>withdraw_writer($withdraw['token']),'prospective withdrawal replay rejected');
$fixture=$directory.'/fake.mp4';file_put_contents($fixture,'<?php echo "malicious";');
denied(fn()=>validate_upload($fixture,filesize($fixture),'Synthetic transcript'),'disguised executable upload rejected');
denied(fn()=>validate_upload($fixture,26*1024*1024,'Synthetic transcript'),'oversize upload rejected');
denied(fn()=>upload_arrival([],''),'upload requires admin authentication');
$r=query("SELECT r.* FROM reminders r JOIN bookings b ON b.id=r.booking_id WHERE b.id=? AND r.type='two_hours'",[$l['id']])->fetch();
check($r['due_at_utc']==='2030-01-12T00:10:00Z','two-hour reminder UTC');
$r=query("SELECT r.* FROM reminders r WHERE booking_id=? AND type='day_of'",[$l['id']])->fetch();
check($r['due_at_utc']==='2030-01-11T19:00:00Z','day-of reminder uses show evening');
$r=query("SELECT * FROM reminders WHERE booking_id=? AND type='check_in_30'",[$l['id']])->fetch();
check($r['due_at_utc']==='2030-01-12T01:20:00Z','reminder is 30 minutes before check-in');
$stats=process_reminders();check($stats['accepted']===0 && $stats['disabled']>0,'disabled transport never claims delivery');
config(['mail_transport'=>'smtp']+config());
$stats=process_reminders(fn()=>throw new RuntimeException('synthetic failure'));
check($stats['failed']>0 && $stats['accepted']===0,'mail failure recorded with bounded retry');
query("UPDATE reminders SET due_at_utc=?,attempt_count=2 WHERE status='failed'",['2000-01-01T00:00:00Z']);
process_reminders(fn()=>throw new RuntimeException('synthetic failure'));
check(process_reminders(fn()=>throw new RuntimeException('synthetic failure'))['failed']===0,'retry count stops at three');
query("UPDATE reminders SET status='pending',due_at_utc=?,attempt_count=0 WHERE booking_id=? AND type='confirmation'",[utc(),$l['id']]);
$calls=0;$stats=process_reminders(function () use (&$calls): void {$calls++;});
check($stats['accepted']===1 && $calls===1,'provider acceptance recorded once');
process_reminders(function () use (&$calls): void {$calls++;});check($calls===1,'worker rerun does not redeliver');
query("UPDATE reminders SET status='sending',claimed_at=? WHERE booking_id=? AND type='confirmation'",['2000-01-01T00:00:00Z',$l['id']]);
check(process_reminders()['uncertain']===1,'crashed send quarantined instead of duplicated');
check(query('PRAGMA integrity_check')->fetchColumn()==='ok','database integrity');

// Two independent PDO connections compete for one slot using actual processes.
if (function_exists('pcntl_fork')) {
    $raceSlot=(int)$slots[2]['id'];$children=[];
    for($i=0;$i<2;$i++) {
        $pid=pcntl_fork();
        if($pid===0) {
            db(true);usleep(50000);
            try {create_booking(payload($raceSlot));$result='booked';} catch(Throwable $e) {$result='rejected';}
            file_put_contents($directory.'/race-'.$i,$result);exit(0);
        }
        $children[]=$pid;
    }
    foreach($children as $child) pcntl_waitpid($child,$status);
    check([file_get_contents($directory.'/race-0'),file_get_contents($directory.'/race-1')]===['booked','rejected']
        || [file_get_contents($directory.'/race-0'),file_get_contents($directory.'/race-1')]===['rejected','booked'],'concurrent processes cannot double-book');
} else echo "SKIP concurrent processes: pcntl unavailable (CI enables it).\n";
echo "{$checks} checks passed. Synthetic database: {$directory}\n";
