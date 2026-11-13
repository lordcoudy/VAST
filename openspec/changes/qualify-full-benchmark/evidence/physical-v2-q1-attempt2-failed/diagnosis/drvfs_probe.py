import os,stat,sys,json,time
d=sys.argv[1]; os.makedirs(d,exist_ok=False)
def ep(i): return dict(dev=i.st_dev,ino=i.st_ino,mode=oct(i.st_mode),nlink=i.st_nlink,size=i.st_size,mtime=i.st_mtime_ns,ctime=i.st_ctime_ns)
res={}
for size in (0,5):
    p=os.path.join(d,f"f{size}")
    fd=os.open(p,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o444)
    if size: os.write(fd,b"x"*size)
    os.fsync(fd); os.close(fd)
    fd=os.open(p,os.O_RDONLY|os.O_NOFOLLOW|os.O_CLOEXEC|os.O_NONBLOCK)
    a=os.fstat(fd); b=os.lstat(p); time.sleep(0.2); c=os.fstat(fd); e=os.lstat(p)
    res[size]={"fstat":ep(a),"lstat":ep(b),"equal_now":ep(a)==ep(b),"fstat_later":ep(c),"lstat_later":ep(e)}
    os.close(fd)
print(json.dumps(res,indent=1))
