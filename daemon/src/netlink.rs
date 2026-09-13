// SPDX-License-Identifier: GPL-2.0 OR Apache-2.0
/*
 * Action Key Assistant - Netlink Socket Listener & Command Sender
 *
 * 封装 Linux 用户态 AF_NETLINK 全双工套接字操作：
 * 1. 监听组 1 接收内核事件 (手势、手电筒状态)；
 * 2. 向内核 (pid 0) 单播下发配置与控制指令。
 */

use crate::protocol::{ActionKeyCmd, ActionKeyEvent, ACTION_KEY_NL_GROUP, NETLINK_ACTION_KEY};
use std::io::{Error, Result};
use std::mem;

pub struct NetlinkListener {
    fd: libc::c_int,
}

impl NetlinkListener {
    /// 创建并绑定 Netlink 套接字
    pub fn bind() -> Result<Self> {
        let fd = unsafe {
            libc::socket(
                libc::AF_NETLINK,
                libc::SOCK_RAW | libc::SOCK_CLOEXEC,
                NETLINK_ACTION_KEY,
            )
        };

        if fd < 0 {
            return Err(Error::last_os_error());
        }

        // 绑定到多播组 1
        let mut sa: libc::sockaddr_nl = unsafe { mem::zeroed() };
        sa.nl_family = libc::AF_NETLINK as u16;
        sa.nl_pid = 0; // 内核分配合适的端口
        sa.nl_groups = ACTION_KEY_NL_GROUP; // 组 1

        let ret = unsafe {
            libc::bind(
                fd,
                &sa as *const libc::sockaddr_nl as *const libc::sockaddr,
                mem::size_of::<libc::sockaddr_nl>() as libc::socklen_t,
            )
        };

        if ret < 0 {
            let err = Error::last_os_error();
            unsafe { libc::close(fd) };
            return Err(err);
        }

        Ok(Self { fd })
    }

    /// 阻塞等待并读取一个手势事件
    pub fn recv_event(&self) -> Result<ActionKeyEvent> {
        let mut buffer = [0u8; 512];
        let bytes_read = unsafe {
            libc::recv(
                self.fd,
                buffer.as_mut_ptr() as *mut libc::c_void,
                buffer.len(),
                0,
            )
        };

        if bytes_read < 0 {
            return Err(Error::last_os_error());
        }

        let nl_msg_hdr_len = mem::size_of::<libc::nlmsghdr>();
        let event_len = mem::size_of::<ActionKeyEvent>();

        if (bytes_read as usize) < nl_msg_hdr_len + event_len {
            return Err(Error::new(
                std::io::ErrorKind::InvalidData,
                "接收到的 Netlink 数据包尺寸过小",
            ));
        }

        // 解析 nlmsghdr 载荷
        let nlh = unsafe { &*(buffer.as_ptr() as *const libc::nlmsghdr) };
        if nlh.nlmsg_type == libc::NLMSG_ERROR as u16 {
            return Err(Error::new(
                std::io::ErrorKind::Other,
                "Netlink 返回 NLMSG_ERROR",
            ));
        }

        // 获取载荷偏移处的数据
        let payload_ptr = unsafe {
            buffer.as_ptr().add(nl_msg_hdr_len) as *const ActionKeyEvent
        };
        let event = unsafe { *payload_ptr };

        Ok(event)
    }

    /// 发送指令给内核
    pub fn send_cmd(&self, cmd: &ActionKeyCmd) -> Result<()> {
        send_cmd_via_fd(self.fd, cmd)
    }
}

impl Drop for NetlinkListener {
    fn drop(&mut self) {
        if self.fd >= 0 {
            unsafe { libc::close(self.fd) };
        }
    }
}

fn send_cmd_via_fd(fd: libc::c_int, cmd: &ActionKeyCmd) -> Result<()> {
    let cmd_len = mem::size_of::<ActionKeyCmd>();
    let nl_msg_hdr_len = mem::size_of::<libc::nlmsghdr>();
    let total_len = nl_msg_hdr_len + cmd_len;

    let mut buffer = vec![0u8; total_len];
    let nlh = unsafe { &mut *(buffer.as_mut_ptr() as *mut libc::nlmsghdr) };
    nlh.nlmsg_len = total_len as u32;
    nlh.nlmsg_type = libc::NLMSG_DONE as u16;
    nlh.nlmsg_flags = 0;
    nlh.nlmsg_seq = 0;
    nlh.nlmsg_pid = std::process::id();

    unsafe {
        let payload_ptr = buffer.as_mut_ptr().add(nl_msg_hdr_len);
        std::ptr::copy_nonoverlapping(cmd as *const _ as *const u8, payload_ptr, cmd_len);
    }

    let mut dest_addr: libc::sockaddr_nl = unsafe { mem::zeroed() };
    dest_addr.nl_family = libc::AF_NETLINK as u16;
    dest_addr.nl_pid = 0; // 内核
    dest_addr.nl_groups = 0;

    let sent = unsafe {
        libc::sendto(
            fd,
            buffer.as_ptr() as *const libc::c_void,
            total_len,
            0,
            &dest_addr as *const libc::sockaddr_nl as *const libc::sockaddr,
            mem::size_of::<libc::sockaddr_nl>() as libc::socklen_t,
        )
    };

    if sent < 0 {
        return Err(Error::last_os_error());
    }
    Ok(())
}

/// 独立的指令下发函数（按需建立套接字发送后关闭，供 WebUI 或独立线程调用）
pub fn send_kernel_cmd(cmd: &ActionKeyCmd) -> Result<()> {
    let fd = unsafe {
        libc::socket(
            libc::AF_NETLINK,
            libc::SOCK_RAW | libc::SOCK_CLOEXEC,
            NETLINK_ACTION_KEY,
        )
    };
    if fd < 0 {
        return Err(Error::last_os_error());
    }

    let res = send_cmd_via_fd(fd, cmd);
    unsafe { libc::close(fd) };
    res
}
