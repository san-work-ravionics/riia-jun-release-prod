export async function loadUsers() {
    const tbody = document.querySelector('#users-table tbody');
    tbody.innerHTML = '<tr><td colspan="7" class="loading">Loading...</td></tr>';
    
    try {
        const res = await fetch('/api/v1/users');

        if (!res.ok) {
            tbody.innerHTML = `<tr><td colspan="7" style="color:var(--danger); text-align:center; padding: 20px;">Failed to load users (${res.status}).</td></tr>`;
            return;
        }
        
        const users = await res.json();
        renderUsersTable(users);
    } catch(e) {
        tbody.innerHTML = `<tr><td colspan="7" style="color:var(--danger); text-align:center;">Failed to load users</td></tr>`;
    }
}

function renderUsersTable(users) {
    const tbody = document.querySelector('#users-table tbody');
    if (!users.length) {
        tbody.innerHTML = '<tr><td colspan="7" style="text-align:center;color:var(--t3); padding:20px;">No users found in database</td></tr>';
        return;
    }
    
    let html = '';
    users.forEach(u => {
        let ld = u.last_login_date ? new Date(u.last_login_date).toLocaleString() : 'Never';
        html += `
        <tr>
            <td style="font-weight:600;">${u.id}</td>
            <td style="font-family:var(--fm); font-size:10px;">${ld}</td>
            <td style="text-align:center"><input type="checkbox" id="chk-assist-${u.id}" ${u.can_assist_research ? 'checked' : ''}></td>
            <td style="text-align:center"><input type="checkbox" id="chk-create-${u.id}" ${u.can_create_portfolio ? 'checked' : ''} disabled title="Open Access Constraint"></td>
            <td style="text-align:center"><input type="checkbox" id="chk-review-${u.id}" ${u.can_review_portfolio ? 'checked' : ''}></td>
            <td style="text-align:center"><input type="checkbox" id="chk-ops-${u.id}" ${u.can_access_ops ? 'checked' : ''}></td>
            <td><button style="font-size:10px; font-weight: 600; padding:4px 8px; border-radius: 4px; border: 1px solid var(--border); background: var(--surface); cursor: pointer;" onclick="saveUserRoles('${u.id}')">Save</button></td>
        </tr>
        `;
    });
    tbody.innerHTML = html;
}

export async function saveUserRoles(userId) {
    const btn = event.target;
    btn.textContent = 'Saving...';
    
    const payload = {
        can_assist_research: document.getElementById(`chk-assist-${userId}`).checked,
        can_create_portfolio: true, // explicitly true as it is open access
        can_review_portfolio: document.getElementById(`chk-review-${userId}`).checked,
        can_access_ops: document.getElementById(`chk-ops-${userId}`).checked
    };
    
    try {
        const res = await fetch(`/api/v1/users/${userId}/roles`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        });
        
        if (res.ok) {
            btn.textContent = 'Saved!';
            btn.style.background = 'var(--ok)';
            btn.style.color = '#fff';
            setTimeout(() => { btn.textContent = 'Save'; btn.style.background = ''; btn.style.color = ''; }, 2000);
        } else {
            btn.textContent = 'Auth Failed';
            setTimeout(() => { btn.textContent = 'Save'; }, 2000);
        }
    } catch(e) {
        btn.textContent = 'Error';
    }
}
