<?php if ($route==='/admin/login'): ?>
<section class="page-heading"><p class="eyebrow">PRIVATE HOST DESK</p><h1>Sign in.</h1></section>
<form method="post" class="panel login"><input type="hidden" name="csrf" value="<?= e(csrf()) ?>">
<label>Host password<input type="password" name="password" maxlength="200" autocomplete="current-password" required></label>
<button class="button" <?= !forms_ready()?'disabled':'' ?>>Sign in</button>
<p>Host credentials are configured outside the web root. <?= !forms_ready()?'Secure sign-in is not yet configured.':'' ?></p></form>
<?php return; endif;
require_admin();
$flash=$_SESSION['notice']??'';unset($_SESSION['notice']);
$nights=query('SELECT * FROM show_nights ORDER BY show_date DESC')->fetchAll();
$tonight=(new DateTimeImmutable('now',new DateTimeZone(BOX2_ZONE)));
if ((int)$tonight->format('H')<3) $tonight=$tonight->modify('-1 day');
$default=query('SELECT id FROM show_nights WHERE show_date>=? ORDER BY show_date LIMIT 1',[$tonight->format('Y-m-d')])->fetchColumn();
$nightId=filter_var($_GET['night']??$_POST['night_id']??$default,FILTER_VALIDATE_INT);
$night=$nightId?query('SELECT * FROM show_nights WHERE id=?',[$nightId])->fetch():false;
function host_hidden(?int $nightId=null): void {echo '<input type="hidden" name="csrf" value="'.e(csrf()).'">';if($nightId) echo '<input type="hidden" name="night_id" value="'.$nightId.'">';}
?>
<section class="page-heading host-heading"><div><p class="eyebrow">PRIVATE — NEVER PROJECT THIS PAGE</p><h1>Host desk.</h1></div>
<form method="post" action="<?= e(url('/admin/logout')) ?>"><?php host_hidden(); ?><button class="secondary">Log out</button></form></section>
<?php if($flash): ?><p class="message" role="status"><?= e($flash) ?></p><?php endif; ?>
<form method="get" class="night-picker"><label for="night">Show night</label><select id="night" name="night">
<?php foreach($nights as $item): ?><option value="<?= (int)$item['id'] ?>" <?= $nightId===$item['id']?'selected':'' ?>><?= e($item['show_date'].' · '.$item['status']) ?></option><?php endforeach; ?></select><button class="secondary">View night</button></form>
<?php if($night): ?>
<section class="panel"><p class="eyebrow">ACTUAL RECORDING STATE</p><h2><?= e($night['recording_mode']) ?></h2>
<p>These controls record your acknowledgment. They cannot operate OBS, Twitch, VOD settings, or recording hardware. Actually stop them before private rehearsal. Live-only sets require VOD and local recording disabled.</p>
<form method="post" action="<?= e(url('/admin/action')) ?>" class="inline-form"><?php host_hidden((int)$nightId); ?><input type="hidden" name="action" value="recording">
<button class="secondary" name="mode" value="confirmed_off">I stopped streaming AND all recording</button><button class="secondary" name="mode" value="public">I resumed public broadcast</button></form></section>
<details class="panel"><summary>Show exception / guest host / adjusted hours</summary>
<form method="post" action="<?= e(url('/admin/action')) ?>"><?php host_hidden((int)$nightId); ?><input type="hidden" name="action" value="override">
<div class="field-grid"><label>Status<select name="status"><option <?= $night['status']==='open'?'selected':'' ?>>open</option><option <?= $night['status']==='closed'?'selected':'' ?>>closed</option></select></label>
<label>Public exception note<input name="override_note" maxlength="300" value="<?= e($night['override_note']) ?>"></label>
<label>Guest host<input name="guest_host" maxlength="100" value="<?= e($night['guest_host']) ?>"></label>
<label>Local start<input type="time" name="start" step="600" value="<?= e((new DateTimeImmutable($night['start_at_utc']))->setTimezone(new DateTimeZone(BOX2_ZONE))->format('H:i')) ?>" required></label>
<label>Local end<input type="time" name="end" step="600" value="<?= e((new DateTimeImmutable($night['end_at_utc']))->setTimezone(new DateTimeZone(BOX2_ZONE))->format('H:i')) ?>" required></label></div>
<p>Occupied slots cannot move. Cancel affected bookings first. New adjusted-hour blocks start held; deliberately open them below.</p><button class="button">Save exception</button></form></details>
<section class="lineup" aria-label="Night lineup">
<?php $bookings=query('SELECT b.*,s.start_at_utc,(SELECT max(allocated.end_at_utc) FROM booking_allocations a JOIN slots allocated ON allocated.id=a.slot_id WHERE a.booking_id=b.id) AS reservation_end_at_utc FROM bookings b JOIN slots s ON s.id=b.slot_id WHERE s.show_night_id=? ORDER BY s.start_at_utc',[$nightId])->fetchAll(); ?>
<?php if(!$bookings): ?><p class="panel">No bookings for this night.</p><?php endif; ?>
<?php foreach($bookings as $booking): ?><?php $stageEnd=utc((new DateTimeImmutable($booking['start_at_utc']))->modify('+'.$booking['duration_minutes'].' minutes'));$arrival=arrival_times($booking['start_at_utc']); ?><article class="panel lineup-card"><div><p class="eyebrow"><?= e(time_range($booking['start_at_utc'],$stageEnd)) ?></p>
<h2><?= e($booking['stage_name']) ?></h2><p><?= e(BOX2_FORMATS[$booking['performance_type']]??$booking['performance_type']) ?> · <strong><?= e($booking['status']) ?></strong></p>
<p><?= (int)$booking['duration_minutes'] ?> minute set · <?= (int)$booking['block_count']*10 ?> calendar minutes reserved through <?= e(local_label($booking['reservation_end_at_utc'])) ?></p>
<p><?= e($booking['consent_level']) ?> · archive <?= $booking['archive_allowed']?'yes':'no' ?> · clips <?= $booking['clips_allowed']?'yes':'no' ?> · adaptation <?= $booking['adaptation_allowed']?'yes':'no' ?> · feedback <?= $booking['feedback_allowed']?'yes':'no' ?></p>
<?php if ($booking['orientation_version']!==BOX2_TERMS): ?><p>Prior orientation acknowledgment: <?= e($booking['orientation_version']) ?>. Review the current arrival policy with this performer before reopening.</p><?php endif; ?>
<p>Arrival window: <?= e(arrival_window($booking['start_at_utc'])) ?>. Check in immediately upon arrival.</p><p>On deck at <?= e(local_label($arrival['on_deck_at_utc'])) ?>.</p>
<details><summary>Private contact / script / host note</summary><p><?= e($booking['full_name']) ?> · <?= e($booking['email']) ?> · <?= e($booking['phone']) ?> · <?= e($booking['social_handle']) ?></p><pre><?= e($booking['teleprompter_text']) ?></pre>
<form method="post" action="<?= e(url('/admin/action')) ?>"><?php host_hidden((int)$nightId); ?><input type="hidden" name="booking_id" value="<?= e($booking['id']) ?>"><input type="hidden" name="action" value="note"><label>Host note<textarea name="host_note" maxlength="1000"><?= e($booking['host_note']) ?></textarea></label><button class="secondary">Save note</button></form></details>
</div><form method="post" action="<?= e(url('/admin/action')) ?>" class="host-actions"><?php host_hidden((int)$nightId); ?><input type="hidden" name="booking_id" value="<?= e($booking['id']) ?>">
<?php if($booking['livestream_allowed']&&!$booking['archive_allowed']): ?><label class="check"><input type="checkbox" name="no_archive_confirmed" value="1">I disabled Twitch VOD and all local recording for this live-only set.</label><?php endif; ?>
<?php foreach(['checked_in'=>'Check in','no_show'=>'No-show','performed'=>'Performed','cancelled'=>'Cancel'] as $action=>$label): ?><button class="secondary" name="action" value="<?= e($action) ?>"><?= e($label) ?></button><?php endforeach; ?>
<?php foreach(BOX2_TAGS as $tag): ?><button class="tag" name="action" value="<?= e($tag) ?>"><?= e(str_replace('_',' ',$tag)) ?> candidate</button><?php endforeach; ?>
<?php $tags=query('SELECT tag FROM clip_candidates WHERE booking_id=?',[$booking['id']])->fetchAll(PDO::FETCH_COLUMN); ?><p>Marked candidates: <?= e(implode(', ',$tags)?:'none') ?>. Review consent before publication.</p></form></article><?php endforeach; ?>
</section>
<details class="panel"><summary>Import an authorized walk-in</summary>
<p>Explain orientation and record the performer's express choices. Do not infer permission from arrival. Bookings must be enabled for this environment; no account is created.</p>
<form method="post" action="<?= e(url('/admin/action')) ?>"><?php host_hidden((int)$nightId); ?><input type="hidden" name="action" value="walk_in"><input type="hidden" name="orientation_version" value="<?= e(BOX2_TERMS) ?>"><label>Set length<select name="duration_minutes"><?php foreach(set_lengths() as $minutes): ?><option value="<?= $minutes ?>"><?= $minutes ?> stage minutes · <?= $minutes*2 ?> calendar minutes</option><?php endforeach; ?></select></label><label>Available start allocation<select name="slot_id" required>
<?php foreach(availability((int)$nightId) as $slot): ?><?php if($slot['state']==='available'||$slot['state']==='held'): ?><option value="<?= (int)$slot['id'] ?>"><?= e(local_label($slot['start_at_utc']).' · '.$slot['visibility']) ?></option><?php endif; ?><?php endforeach; ?></select></label>
<div class="field-grid"><label>Stage name<input name="stage_name" maxlength="100" required></label><label>Email<input name="email" type="email" maxlength="254" required></label><label>Format<select name="performance_type"><?php foreach(BOX2_FORMATS as $key=>$label): ?><option value="<?= e($key) ?>"><?= e($label) ?></option><?php endforeach; ?></select></label></div>
<?php foreach(['livestream','archive','clips','adaptation','feedback'] as $permission): ?><label class="check"><input type="checkbox" name="<?= e($permission) ?>_allowed" value="1">Performer explicitly permits <?= e($permission) ?>.</label><?php endforeach; ?>
<label class="check"><input type="checkbox" name="orientation_agreed" value="1" required>Performer acknowledged all nine current orientation cards, including T−20 to T−10 arrival and check-in upon arrival.</label><label class="check"><input type="checkbox" name="terms_agreed" value="1" required>Performer accepted current terms and selected grants.</label>
<button class="button">Book authorized walk-in</button></form></details>
<details class="panel"><summary>Slot holds / public / private</summary>
<div class="host-slots"><?php foreach(availability((int)$nightId) as $slot): ?><form method="post" action="<?= e(url('/admin/action')) ?>"><?php host_hidden((int)$nightId); ?><input type="hidden" name="action" value="slot"><input type="hidden" name="slot_id" value="<?= (int)$slot['id'] ?>"><label><?= e(local_label($slot['start_at_utc'])) ?> · <?= e($slot['state']) ?><select name="visibility"><?php foreach(['public','hold','private'] as $visibility): ?><option <?= $visibility===$slot['visibility']?'selected':'' ?>><?= e($visibility) ?></option><?php endforeach; ?></select></label><button class="secondary">Save</button></form><?php endforeach; ?></div>
</details>
<section class="panel"><h2>Cleaning record</h2><p>Between performers: compatible mic/contact-surface cleaning. Hourly: lobby and stage-left bathroom high-touch surfaces. Follow manufacturer instructions and actual product contact time.</p>
<form method="post" action="<?= e(url('/admin/action')) ?>" class="inline-form"><?php host_hidden((int)$nightId); ?><input type="hidden" name="action" value="sanitation"><?php foreach(['mic','lobby','bathroom'] as $location): ?><button class="secondary" name="location" value="<?= e($location) ?>">Confirm <?= e($location) ?> cleaned</button><?php endforeach; ?></form>
<ul><?php foreach(query('SELECT location,created_at FROM sanitation_checks WHERE show_night_id=? ORDER BY created_at DESC LIMIT 12',[$nightId])->fetchAll() as $clean): ?><li><?= e($clean['location'].' · '.local_label($clean['created_at'])) ?></li><?php endforeach; ?></ul></section>
<?php endif; ?>
<section class="panel"><h2>Private writer desk</h2>
<?php foreach(query('SELECT * FROM writer_submissions ORDER BY created_at DESC LIMIT 50')->fetchAll() as $writer): ?><article class="writer"><h3><?= e($writer['alias']) ?> · <?= e($writer['status']) ?></h3><p>Preferred credit: <?= e($writer['credit']) ?> · Contact: <?= e($writer['contact']) ?></p><pre><?= e($writer['text']) ?></pre><p>Grants: performance <?= $writer['perform_allowed']?'yes':'no' ?> / publication <?= $writer['publish_allowed']?'yes':'no' ?> / AI <?= $writer['ai_allowed']?'yes':'no' ?> / music <?= $writer['music_allowed']?'yes':'no' ?></p>
<p>Do not use withdrawn writing. A grant for one medium does not authorize another.</p>
<?php if($writer['status']==='submitted'): ?><form method="post" action="<?= e(url('/admin/action')) ?>"><?php host_hidden(); ?><input type="hidden" name="action" value="writer_production"><input type="hidden" name="writer_id" value="<?= e($writer['id']) ?>"><button class="secondary">Mark production begun after reviewing grants</button></form><?php endif; ?></article><?php endforeach; ?>
</section>
<section class="panel"><h2>Arrival walkthrough upload</h2><p>MP4/WebM up to 25 MB. Reviewed text transcript required. Public serving remains disabled until venue publication is enabled.</p>
<form method="post" enctype="multipart/form-data" action="<?= e(url('/admin/action')) ?>"><?php host_hidden(); ?><input type="hidden" name="action" value="upload"><label>Video<input type="file" name="video" accept="video/mp4,video/webm" required></label><label>Approved parking / walking / entry transcript<textarea name="transcript" maxlength="10000" rows="5" required></textarea></label><button class="button">Upload reviewed walkthrough</button></form></section>
<section class="panel"><h2>Email diagnostics</h2><p>Transport: <?= e(config()['mail_transport']) ?>. Accepted means provider acceptance, not proven recipient delivery. Interrupted sends are quarantined as uncertain; verify with provider before requeuing.</p>
<table><thead><tr><th>Booking</th><th>Reminder</th><th>State</th><th>Attempts</th></tr></thead><tbody><?php foreach(query('SELECT booking_id,type,status,attempt_count FROM reminders ORDER BY id DESC LIMIT 40')->fetchAll() as $reminder): ?><tr><td><?= e($reminder['booking_id']) ?></td><td><?= e(match($reminder['type']){'check_in_30'=>'arrival reminder','stage_10'=>'on-deck cue',default=>str_replace('_',' ',$reminder['type'])}) ?></td><td><?= e($reminder['status']) ?></td><td><?= (int)$reminder['attempt_count'] ?></td></tr><?php endforeach; ?></tbody></table></section>
