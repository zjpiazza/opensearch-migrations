import java.nio.file.*;
import java.lang.reflect.Proxy;
import java.util.*;
import java.util.concurrent.*;
import java.util.concurrent.atomic.*;
import org.opensearch.migrations.bulkload.common.SnapshotShardUnpacker;
import org.opensearch.migrations.bulkload.models.ShardFileInfo;
import shadow.lucene9.org.apache.lucene.util.BytesRef;
import reactor.core.scheduler.Schedulers;
public class UnpackProbe {
 public static void main(String[] args) throws Exception {
  System.out.println("processors="+Runtime.getRuntime().availableProcessors()+" elasticCap="+Schedulers.DEFAULT_BOUNDED_ELASTIC_SIZE);
  for(int attempt=0;attempt<3;attempt++) {
   var files=new LinkedHashSet<ShardFileInfo>();
   for(int i=0;i<13;i++) {
    final String name="v__file"+i;
    files.add((ShardFileInfo)Proxy.newProxyInstance(UnpackProbe.class.getClassLoader(),new Class[]{ShardFileInfo.class},(p,m,a)->switch(m.getName()) {
     case "getName","getPhysicalName" -> name;
     case "getLength" -> 1L;
     case "getMetaHash" -> new BytesRef(new byte[]{42});
     case "hashCode" -> name.hashCode();
     case "equals" -> p==a[0];
     default -> throw new UnsupportedOperationException(m.getName());
    }));
   }
   Path dir=Files.createTempDirectory("unpack-probe-");
   var done=new CountDownLatch(1); var error=new AtomicReference<Throwable>();
   var job=Schedulers.boundedElastic().schedule(()->{try { new SnapshotShardUnpacker(null,files,dir,"index",0).unpack(); }catch(Throwable e){error.set(e);}finally{done.countDown();}});
   boolean completed=done.await(3,TimeUnit.SECONDS);
   long count;try(var stream=Files.list(dir)){count=stream.count();}
   System.out.println("attempt="+attempt+" completed="+completed+" files="+count+" error="+error.get());
   if(!completed && attempt==0) Thread.getAllStackTraces().forEach((t,s)-> {if(Arrays.stream(s).anyMatch(x->x.getClassName().contains("SnapshotShardUnpacker"))){System.out.println(t.getName()+" "+t.getState());for(var f:s)System.out.println("  "+f);}});
   job.dispose();Schedulers.shutdownNow();
  }
 }
}
