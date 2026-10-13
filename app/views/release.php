<?php if (!$result): ?><section class="panel"><h1>Compilation permissions</h1><p>Use your private release link. No public candidate directory is available.</p></section>
<?php elseif (isset($result['withdrawn'])): ?><section class="panel"><h1>Future permission withdrawn.</h1><p>Unposted selections are removed. Posted URLs are flagged for host removal review; copies already distributed cannot be guaranteed erased.</p></section>
<?php elseif (isset($result['withdrawal'])): ?><section class="panel"><h1>Your choices are recorded.</h1><p>No clip was rendered or posted. Keep this private link to withdraw future permission or request removal: <a href="<?= e($result['withdrawal']) ?>">Withdraw / removal request</a>.</p></section>
<?php else: ?>
<?php $authorization=$result['authorization'];$candidate=editorial_candidate($authorization['candidate_id']); ?>
<section class="page-heading"><p class="eyebrow">PRIVATE CLIP-SPECIFIC RELEASE</p><h1>Your choices.</h1></section>
<section class="panel"><h2><?= $authorization['purpose']==='withdraw'?'Withdraw future permission / request removal':'One weekly organic Top 5 compilation' ?></h2>
<p>Week: <?= e($candidate['week_date']) ?> · Candidate code: <?= e($candidate['id']) ?> · <?= e($candidate['title']) ?></p>
<p>Timecode: <?= number_format($candidate['in_ms']/1000,3) ?>–<?= number_format($candidate['out_ms']/1000,3) ?> seconds in the separately reviewed source recording. Role: <?= e($authorization['role']) ?>.</p>
<form method="post" action="<?= e(url('/release')) ?>"><input type="hidden" name="csrf" value="<?= e(csrf()) ?>">
<?php foreach (['purpose','token','signature'] as $key): ?><input type="hidden" name="<?= e($key) ?>" value="<?= e($result['link_fields'][$key]) ?>"><?php endforeach; ?>
<?php if ($authorization['purpose']==='grant'): ?>
<p>This release applies only to this moment in one BOX2 weekly compilation, organically shared to the destinations you choose. It does not grant ownership, paid/boosted ads, sponsor endorsements, AI/music adaptation, or permission to publish another performer.</p>
<fieldset><legend>Each permission starts OFF</legend>
<?php foreach(TOP5_PLATFORMS as $key=>$label): ?><label class="check"><input type="checkbox" name="<?= e($key) ?>" value="1">I permit this weekly organic compilation on <?= e($label) ?>.</label><?php endforeach; ?>
<?php if($authorization['role']==='performer'): ?><label class="check"><input type="checkbox" name="face_voice" value="1">I permit my face and voice in this specific compilation moment.</label><?php endif; ?>
<label class="check"><input type="checkbox" name="credit_allowed" value="1">I independently permit the public credit / handle entered below.</label>
<label>Chosen public credit (only if permitted)<input name="public_credit" maxlength="100" autocomplete="off"></label>
<label>Approved public handle (optional)<input name="public_handle" maxlength="100" autocomplete="off"></label>
<label class="check"><input type="checkbox" name="scope_acknowledged" value="1" required>I understand this exact scope and retain ownership. Inclusion is not guaranteed; preview/objection handling is manual, and third-party copies may persist.</label>
</fieldset><button class="button">Record only my choices</button>
<?php else: ?><p>Before posting, this removes future selection. After posting, it requests manual removal within BOX2's control, not guaranteed third-party erasure.</p><button class="button">Withdraw / request removal</button><?php endif; ?>
</form></section>
<?php endif; ?>
